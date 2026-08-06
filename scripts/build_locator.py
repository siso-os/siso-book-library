#!/usr/bin/env python3
"""Index exact tar member offsets, lengths, encodings, and SHA-256 digests.

Re-indexing a container is a source replacement: old rows for that container are
deleted inside the same transaction before current members are inserted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tarfile
import time
from pathlib import Path

try:
    from scripts.common import (
        LOADER_VERSION,
        canonical_json,
        sha256_file,
        write_public_receipt_atomic,
    )
except ModuleNotFoundError:
    from common import (  # type: ignore
        LOADER_VERSION,
        canonical_json,
        sha256_file,
        write_public_receipt_atomic,
    )

LOCATOR_SCHEMA_VERSION = "payload-locator-2"
SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS container (
  container TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  uri TEXT,
  sha256 TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  members INTEGER NOT NULL,
  indexed_at TEXT NOT NULL,
  loader_version TEXT NOT NULL,
  schema_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS location (
  gid INTEGER NOT NULL,
  container TEXT NOT NULL REFERENCES container(container) ON DELETE CASCADE,
  member TEXT NOT NULL,
  offset INTEGER NOT NULL CHECK(offset >= 0),
  length INTEGER NOT NULL CHECK(length >= 0),
  encoding TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  route TEXT NOT NULL CHECK(route IN ('local','release')),
  uri TEXT NOT NULL,
  indexed_at TEXT NOT NULL,
  PRIMARY KEY (gid, container, route)
);
CREATE INDEX IF NOT EXISTS ix_loc_gid ON location(gid);
CREATE INDEX IF NOT EXISTS ix_loc_route ON location(route);
"""
GID = re.compile(r"(?:^|/)(?:pg)?(\d+)(?:-\d+)?\.txt(?:\.gz)?$", re.IGNORECASE)

EXPECTED_COLUMNS = {
    "container": {
        "container", "path", "uri", "sha256", "bytes", "members",
        "indexed_at", "loader_version", "schema_version",
    },
    "location": {
        "gid", "container", "member", "offset", "length", "encoding",
        "payload_sha256", "route", "uri", "indexed_at",
    },
}


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _ensure_schema(connection: sqlite3.Connection) -> None:
    existing = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    managed = existing & set(EXPECTED_COLUMNS)
    if managed:
        for table, expected in EXPECTED_COLUMNS.items():
            actual = _table_columns(connection, table)
            if actual != expected:
                raise RuntimeError(
                    "locator database uses an incompatible derived schema; "
                    "regenerate it into a fresh file with build_locator.py "
                    f"(table {table}: expected {sorted(expected)}, got {sorted(actual)})"
                )
    connection.executescript(SCHEMA)


def _logical_digest(members: list[tuple[int, str, int, int, str, str]]) -> str:
    digest = hashlib.sha256()
    for row in sorted(members):
        digest.update(canonical_json(list(row)).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def gid_from(member: str) -> int | None:
    match = GID.search(member)
    return int(match.group(1)) if match else None


def _hash_member(tar: tarfile.TarFile, info: tarfile.TarInfo) -> str:
    extracted = tar.extractfile(info)
    if extracted is None:
        raise ValueError(f"unable to read tar member {info.name}")
    digest = hashlib.sha256()
    for chunk in iter(lambda: extracted.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def build(
    tar_path: str,
    db_path: str,
    container_name: str = "gutenberg-payload",
    local_uri: str | None = None,
    release_uri: str | None = None,
    indexed_at: str | None = None,
    manifest_out: str | None = None,
) -> dict[str, object]:
    archive = Path(tar_path)
    if not archive.is_file():
        raise FileNotFoundError(archive)
    now = indexed_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    container_digest = sha256_file(archive)
    local = local_uri or str(archive)

    members: list[tuple[int, str, int, int, str, str]] = []
    duplicate_gids: set[int] = set()
    seen_gids: set[int] = set()
    skipped = 0
    with tarfile.open(archive, "r:") as tar:
        for info in tar:
            if not info.isfile():
                continue
            gid = gid_from(info.name)
            if gid is None:
                skipped += 1
                continue
            if gid in seen_gids:
                duplicate_gids.add(gid)
                continue
            seen_gids.add(gid)
            encoding = "gzip" if info.name.casefold().endswith(".gz") else "identity"
            members.append(
                (
                    gid,
                    info.name,
                    int(info.offset_data),
                    int(info.size),
                    encoding,
                    _hash_member(tar, info),
                )
            )
    if duplicate_gids:
        raise ValueError(f"duplicate Gutenberg IDs in container: {sorted(duplicate_gids)[:10]}")

    connection = sqlite3.connect(db_path)
    try:
        _ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM container WHERE container = ?", (container_name,))
        connection.execute(
            "INSERT INTO container VALUES (?,?,?,?,?,?,?,?,?)",
            (
                container_name,
                str(archive),
                release_uri,
                container_digest,
                archive.stat().st_size,
                len(members),
                now,
                LOADER_VERSION,
                LOCATOR_SCHEMA_VERSION,
            ),
        )
        local_rows = [
            (
                gid, container_name, member, offset, length, encoding, digest,
                "local", local, now,
            )
            for gid, member, offset, length, encoding, digest in members
        ]
        connection.executemany(
            "INSERT INTO location VALUES (?,?,?,?,?,?,?,?,?,?)", local_rows
        )
        if release_uri:
            release_rows = [
                (
                    gid, container_name, member, offset, length, encoding, digest,
                    "release", release_uri, now,
                )
                for gid, member, offset, length, encoding, digest in members
            ]
            connection.executemany(
                "INSERT INTO location VALUES (?,?,?,?,?,?,?,?,?,?)", release_rows
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    locator_digest = _logical_digest(members)
    route_count = 1 + (1 if release_uri else 0)
    manifest: dict[str, object] = {
        "manifest_version": "book-library-locator-1",
        "container": container_name,
        "tar": str(archive),
        "tar_sha256": container_digest,
        "tar_bytes": archive.stat().st_size,
        "members": len(members),
        "logical_digest": locator_digest,
        "row_counts": {"container": 1, "location": len(members) * route_count},
        "routes": ["local"] + (["release"] if release_uri else []),
        "skipped_members_without_gid": skipped,
        "loader_version": LOADER_VERSION,
        "schema_version": LOCATOR_SCHEMA_VERSION,
        "database": db_path,
    }
    if manifest_out:
        write_public_receipt_atomic(manifest_out, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tar", required=True)
    parser.add_argument("--db", default="locator.sqlite")
    parser.add_argument("--container", default="gutenberg-payload")
    parser.add_argument("--local-uri")
    parser.add_argument("--release-uri")
    parser.add_argument("--indexed-at")
    parser.add_argument("--manifest-out")
    arguments = parser.parse_args()
    print(json.dumps(build(
        tar_path=arguments.tar,
        db_path=arguments.db,
        container_name=arguments.container,
        local_uri=arguments.local_uri,
        release_uri=arguments.release_uri,
        indexed_at=arguments.indexed_at,
        manifest_out=arguments.manifest_out,
    ), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
