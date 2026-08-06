#!/usr/bin/env python3
"""Standard-library helpers shared by the Book Library integrity tools."""
from __future__ import annotations

import contextlib
import csv
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class ContractError(ValueError):
    """Raised when a source, build, or export contract is invalid."""


def nfc(value: str | None) -> str:
    return unicodedata.normalize("NFC", value or "")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: os.PathLike[str] | str, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def require_sha256(value: str, field: str) -> str:
    if not SHA256_RE.fullmatch(value or ""):
        raise ContractError(f"{field} must be a lowercase 64-character SHA-256")
    return value


def require_iso_utc(value: str, field: str) -> str:
    if not ISO_UTC_RE.fullmatch(value or ""):
        raise ContractError(f"{field} must be an ISO-8601 UTC timestamp ending in Z")
    return value


def require_fields(value: Mapping[str, Any], fields: Iterable[str], context: str) -> None:
    missing = [field for field in fields if field not in value]
    if missing:
        raise ContractError(f"{context} missing fields: {', '.join(sorted(missing))}")


def read_json(path: os.PathLike[str] | str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: os.PathLike[str] | str, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(target, payload)


def atomic_write_bytes(path: os.PathLike[str] | str, payload: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary_name)
        raise


@contextlib.contextmanager
def atomic_database_path(path: os.PathLike[str] | str) -> Iterator[Path]:
    """Build a fresh sibling SQLite file and replace the destination on success.

    Full replacement is the source-reconciliation policy: rows, fields, edges,
    facets, and views absent from the new snapshot cannot survive from an older
    run. The destination remains untouched when validation fails.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".sqlite", dir=target.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    with contextlib.suppress(FileNotFoundError):
        temporary.unlink()
    try:
        yield temporary
        with contextlib.closing(sqlite3.connect(temporary)) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ContractError(f"SQLite integrity_check failed for {temporary}: {integrity}")
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_keys:
                raise ContractError(
                    f"SQLite foreign_key_check failed for {temporary}: {foreign_keys[:5]}"
                )
        os.replace(temporary, target)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _sqlite_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"$bytes_hex": value.hex()}
    return value


def sqlite_table_names(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [row[0] for row in rows]


def sqlite_logical_snapshot(
    db_path: os.PathLike[str] | str,
    *,
    include_tables: Sequence[str] | None = None,
    exclude_tables: Iterable[str] = (),
) -> dict[str, Any]:
    """Digest logical rows, not SQLite page layout.

    The digest covers table names, ordered columns, and canonical JSON rows sorted
    by every column. ``binary_sha256`` is reported as a receipt, but logical SHA-256
    is the cross-platform equivalence contract.
    """
    excluded = set(exclude_tables)
    digest = hashlib.sha256()
    counts: dict[str, int] = {}
    with sqlite_readonly(db_path) as connection:
        tables = list(include_tables) if include_tables is not None else sqlite_table_names(connection)
        for table in sorted(table for table in tables if table not in excluded):
            columns = [
                row[1]
                for row in connection.execute(
                    f"PRAGMA table_info({quote_identifier(table)})"
                )
            ]
            if not columns:
                continue
            digest.update(
                (canonical_json({"table": table, "columns": columns}) + "\n").encode("utf-8")
            )
            order = ", ".join(quote_identifier(column) for column in columns)
            query = f"SELECT * FROM {quote_identifier(table)} ORDER BY {order}"
            count = 0
            for row in connection.execute(query):
                payload = {column: _sqlite_value(row[column]) for column in columns}
                digest.update((canonical_json(payload) + "\n").encode("utf-8"))
                count += 1
            counts[table] = count
    return {
        "logical_sha256": digest.hexdigest(),
        "table_counts": counts,
        "row_count": sum(counts.values()),
        "binary_sha256": sha256_file(db_path),
        "authoritative_equivalence": "logical_sha256",
    }


def load_source_manifest(path: os.PathLike[str] | str) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    manifest = read_json(manifest_path)
    if not isinstance(manifest, Mapping):
        raise ContractError("source manifest must be a JSON object")
    required = {
        "manifest_version",
        "source_id",
        "snapshot_id",
        "source_uri",
        "source_observed_at",
        "retrieved_at",
        "terms_revision",
        "rights_state",
        "rights_basis",
        "acquisition_method",
        "payload_path",
        "payload_sha256",
        "expected_row_contract",
        "raw_pointer_template",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise ContractError(f"source manifest missing fields: {', '.join(missing)}")
    if manifest["manifest_version"] != "book-source-1":
        raise ContractError("unsupported source manifest_version")
    require_iso_utc(str(manifest["source_observed_at"]), "source_observed_at")
    require_iso_utc(str(manifest["retrieved_at"]), "retrieved_at")
    require_sha256(str(manifest["payload_sha256"]), "payload_sha256")
    payload_path = (manifest_path.parent / str(manifest["payload_path"])).resolve()
    if not payload_path.is_file():
        raise ContractError(f"source payload does not exist: {payload_path}")
    actual = sha256_file(payload_path)
    if actual != manifest["payload_sha256"]:
        raise ContractError(
            f"source payload digest mismatch: manifest={manifest['payload_sha256']} actual={actual}"
        )
    contract = manifest["expected_row_contract"]
    if not isinstance(contract, Mapping):
        raise ContractError("expected_row_contract must be an object")
    required_columns = contract.get("required_columns")
    if not isinstance(required_columns, list) or not required_columns:
        raise ContractError(
            "expected_row_contract.required_columns must be a non-empty list"
        )
    with open(payload_path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ContractError("source payload is empty") from exc
    absent = sorted(set(required_columns) - set(header))
    if absent:
        raise ContractError(f"source payload missing required columns: {absent}")
    enriched = dict(manifest)
    enriched["_manifest_path"] = str(manifest_path)
    enriched["_payload_path"] = str(payload_path)
    enriched["_manifest_sha256"] = sha256_file(manifest_path)
    return enriched


@contextlib.contextmanager
def sqlite_readonly(path: os.PathLike[str] | str) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.row_factory = sqlite3.Row
        yield connection
    finally:
        connection.close()
