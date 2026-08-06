#!/usr/bin/env python3
"""Shared deterministic-build helpers for the Book Library."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Iterable, Iterator, Sequence

LOADER_VERSION = "book-library-integrity-1.0"
SCHEMA_VERSION = "books-index-2"

# Runtime locations make receipts non-reproducible and can expose private build
# topology.  They remain available in in-process return values and CLI output,
# but are removed from manifests intended for handoff or publication.
RUNTIME_ONLY_MANIFEST_KEYS = frozenset({
    "database",
    "output",
    "source_path",
    "tar",
})


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: str | os.PathLike[str], value: object) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, destination)


def public_receipt(value: object) -> object:
    """Return a path-independent, public-safe copy of a manifest value.

    Component builders may return local paths so a caller can find newly built
    artifacts. Those locations are execution details, not part of the logical
    release contract. Recursively removing the explicitly runtime-only keys
    keeps written receipts reproducible across checkout and temporary paths.
    """

    if isinstance(value, dict):
        return {
            str(key): public_receipt(child)
            for key, child in value.items()
            if str(key) not in RUNTIME_ONLY_MANIFEST_KEYS
        }
    if isinstance(value, list):
        return [public_receipt(child) for child in value]
    return value


def write_public_receipt_atomic(
    path: str | os.PathLike[str], value: object
) -> None:
    """Write a deterministic manifest without runtime-only local paths."""

    write_json_atomic(path, public_receipt(value))


@contextlib.contextmanager
def atomic_sqlite_target(path: str | os.PathLike[str]) -> Iterator[Path]:
    """Yield a sibling temporary path and atomically replace the destination.

    Rebuilding from a source snapshot rather than mutating a prior database is
    the source-replacement contract: rows removed upstream cannot linger.
    """

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        yield temporary
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def logical_digest(
    connection: sqlite3.Connection,
    table_columns: Sequence[tuple[str, Sequence[str]]],
) -> str:
    """Digest stable logical rows, excluding SQLite layout and volatile fields."""

    digest = hashlib.sha256()
    for table, columns in table_columns:
        quoted = ", ".join(f'"{column}"' for column in columns)
        order = ", ".join(f'"{column}"' for column in columns)
        digest.update(f"table:{table}\n".encode())
        cursor = connection.execute(
            f'SELECT {quoted} FROM "{table}" ORDER BY {order}'
        )
        for row in cursor:
            digest.update(canonical_json(list(row)).encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest()


def table_counts(
    connection: sqlite3.Connection, tables: Iterable[str]
) -> dict[str, int]:
    return {
        table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in tables
    }
