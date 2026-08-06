#!/usr/bin/env python3
"""Index exact byte ranges and checksums for Book Library payload members.

Supported release assets are uncompressed tar files containing one ``.txt.gz``
member per Work. ``offset`` and ``length`` address the compressed member bytes;
``content_sha256`` addresses decompressed book bytes. Re-indexing a container
deletes its old rows first, so stale members cannot survive source replacement.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sqlite3
import sys
import tarfile
from pathlib import Path
from typing import Any

from booklib import LOADER_VERSION
from booklib.common import (
    ContractError,
    canonical_json,
    require_iso_utc,
    sha256_bytes,
    sha256_file,
    sqlite_readonly,
)

LOCATOR_SCHEMA_VERSION = "book-locator-1.0"
SCHEMA = """
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=DELETE;
PRAGMA synchronous=FULL;
PRAGMA user_version=100;

CREATE TABLE IF NOT EXISTS container (
  container      TEXT PRIMARY KEY,
  stored_path    TEXT NOT NULL,
  uri            TEXT NOT NULL,
  bytes          INTEGER NOT NULL CHECK(bytes >= 0),
  members        INTEGER NOT NULL CHECK(members >= 0),
  sha256         TEXT NOT NULL CHECK(length(sha256) = 64),
  indexed_at     TEXT NOT NULL,
  loader_version TEXT NOT NULL,
  schema_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS location (
  gid                 INTEGER NOT NULL,
  container           TEXT NOT NULL REFERENCES container(container) ON DELETE CASCADE,
  member              TEXT NOT NULL,
  offset              INTEGER NOT NULL CHECK(offset >= 0),
  length              INTEGER NOT NULL CHECK(length >= 0),
  uncompressed_length INTEGER NOT NULL CHECK(uncompressed_length >= 0),
  compression         TEXT NOT NULL CHECK(compression IN ('gzip','none')),
  content_sha256      TEXT NOT NULL CHECK(length(content_sha256) = 64),
  member_sha256       TEXT NOT NULL CHECK(length(member_sha256) = 64),
  route               TEXT NOT NULL,
  uri                 TEXT NOT NULL,
  indexed_at          TEXT NOT NULL,
  PRIMARY KEY (gid, container, route)
);
CREATE INDEX IF NOT EXISTS ix_location_gid ON location(gid);
CREATE INDEX IF NOT EXISTS ix_location_route ON location(route);
"""

EXPECTED_CONTAINER_COLUMNS = {
    "container",
    "stored_path",
    "uri",
    "bytes",
    "members",
    "sha256",
    "indexed_at",
    "loader_version",
    "schema_version",
}
EXPECTED_LOCATION_COLUMNS = {
    "gid",
    "container",
    "member",
    "offset",
    "length",
    "uncompressed_length",
    "compression",
    "content_sha256",
    "member_sha256",
    "route",
    "uri",
    "indexed_at",
}
MEMBER_GID = re.compile(r"(?:^|/)(?:pg)?(\d+)(?:-\d+)?\.txt(?P<gzip>\.gz)?$", re.I)


def gid_from(member: str) -> tuple[int, str] | None:
    match = MEMBER_GID.search(member)
    if not match:
        return None
    return int(match.group(1)), "gzip" if match.group("gzip") else "none"


def _check_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    container_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(container)")
    }
    location_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(location)")
    }
    if container_columns != EXPECTED_CONTAINER_COLUMNS or location_columns != EXPECTED_LOCATION_COLUMNS:
        raise ContractError(
            "existing locator schema is incompatible; regenerate locator.sqlite "
            "with the tracked pack/index tools"
        )


def locator_logical_snapshot(db_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Digest portable locator facts, excluding local machine topology."""
    digest = hashlib.sha256()
    counts: dict[str, int] = {}
    with sqlite_readonly(db_path) as connection:
        container_rows = connection.execute(
            "SELECT container,uri,bytes,members,sha256,indexed_at,loader_version,schema_version "
            "FROM container ORDER BY container"
        )
        count = 0
        for row in container_rows:
            digest.update((canonical_json(dict(row)) + "\n").encode("utf-8"))
            count += 1
        counts["container"] = count
        location_rows = connection.execute(
            "SELECT gid,container,member,offset,length,uncompressed_length,compression,"
            "content_sha256,member_sha256,route,uri,indexed_at "
            "FROM location ORDER BY container,route,gid"
        )
        count = 0
        for row in location_rows:
            digest.update((canonical_json(dict(row)) + "\n").encode("utf-8"))
            count += 1
        counts["location"] = count
    return {
        "logical_sha256": digest.hexdigest(),
        "table_counts": counts,
        "row_count": sum(counts.values()),
        "binary_sha256": sha256_file(db_path),
        "authoritative_equivalence": "logical_sha256_excluding_stored_path",
    }


def build(
    tar_path: str | os.PathLike[str],
    db_path: str | os.PathLike[str],
    *,
    container_name: str,
    uri: str | None = None,
    stored_path: str | None = None,
    indexed_at: str,
    route: str = "local",
    limit: int = 0,
) -> dict[str, Any]:
    require_iso_utc(indexed_at, "indexed_at")
    archive_path = Path(tar_path).resolve()
    if not archive_path.is_file():
        raise ContractError(f"payload asset does not exist: {archive_path}")
    database_path = Path(db_path).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    container_uri = uri or archive_path.name
    portable_path = stored_path or archive_path.name
    container_sha = sha256_file(archive_path)

    rows: list[tuple[Any, ...]] = []
    seen_gids: set[int] = set()
    scanned = skipped = 0
    # ``r:`` deliberately rejects compressed tar containers: offsets in a .tar.gz
    # are not direct member ranges and therefore cannot satisfy this contract.
    with tarfile.open(archive_path, mode="r:") as archive, archive_path.open("rb") as raw_file:
        for info in archive:
            if not info.isfile():
                continue
            scanned += 1
            parsed = gid_from(info.name)
            if parsed is None:
                skipped += 1
                continue
            gid, compression = parsed
            if gid in seen_gids:
                raise ContractError(f"duplicate gid {gid} in {archive_path}")
            seen_gids.add(gid)
            raw_file.seek(info.offset_data)
            member_payload = raw_file.read(info.size)
            if len(member_payload) != info.size:
                raise ContractError(
                    f"short range read for {info.name}: header={info.size} actual={len(member_payload)}"
                )
            try:
                content = gzip.decompress(member_payload) if compression == "gzip" else member_payload
            except (gzip.BadGzipFile, EOFError, OSError) as exc:
                raise ContractError(f"invalid gzip member {info.name}") from exc
            rows.append(
                (
                    gid,
                    container_name,
                    info.name,
                    int(info.offset_data),
                    int(info.size),
                    len(content),
                    compression,
                    sha256_bytes(content),
                    sha256_bytes(member_payload),
                    route,
                    container_uri,
                    indexed_at,
                )
            )
            if limit and len(rows) >= limit:
                break

    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        _check_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM container WHERE container=?", (container_name,))
        connection.execute(
            "INSERT INTO container VALUES (?,?,?,?,?,?,?,?,?)",
            (
                container_name,
                portable_path,
                container_uri,
                archive_path.stat().st_size,
                len(rows),
                container_sha,
                indexed_at,
                LOADER_VERSION,
                LOCATOR_SCHEMA_VERSION,
            ),
        )
        connection.executemany(
            "INSERT INTO location VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )
        failures = connection.execute("PRAGMA foreign_key_check").fetchall()
        if failures:
            raise ContractError(f"foreign key check failed: {failures[:5]}")
        connection.commit()
    except BaseException:
        connection.rollback()
        connection.close()
        raise
    total = connection.execute("SELECT COUNT(*) FROM location").fetchone()[0]
    current = connection.execute(
        "SELECT COUNT(*) FROM location WHERE container=?", (container_name,)
    ).fetchone()[0]
    connection.close()

    return {
        "schema_version": LOCATOR_SCHEMA_VERSION,
        "loader_version": LOADER_VERSION,
        "database": str(database_path),
        "container": container_name,
        "container_sha256": container_sha,
        "members_scanned": scanned,
        "members_indexed": current,
        "members_skipped_without_gid": skipped,
        "locations_total": total,
        "range_semantics": "offset and length address compressed member bytes",
        "content_checksum_semantics": "content_sha256 covers decompressed Work bytes",
        **locator_logical_snapshot(database_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tar", required=True)
    parser.add_argument("--db", default="locator.sqlite")
    parser.add_argument("--container", required=True)
    parser.add_argument("--uri")
    parser.add_argument("--stored-path")
    parser.add_argument("--indexed-at", required=True)
    parser.add_argument("--route", default="local")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        result = build(
            args.tar,
            args.db,
            container_name=args.container,
            uri=args.uri,
            stored_path=args.stored_path,
            indexed_at=args.indexed_at,
            route=args.route,
            limit=args.limit,
        )
    except (ContractError, OSError, sqlite3.Error, tarfile.TarError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
