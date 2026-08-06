#!/usr/bin/env python3
"""Verify tar offsets, lengths, hashes, gzip content, and locator coverage."""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
import tarfile
from pathlib import Path

try:
    from scripts.common import canonical_json, sha256_bytes, sha256_file
except ModuleNotFoundError:  # direct execution from scripts/
    from common import canonical_json, sha256_bytes, sha256_file  # type: ignore


def _logical_input_digest(rows: list[dict[str, object]]) -> str:
    stable = [
        {
            "gid": int(row["gid"]),
            "uncompressed_bytes": int(row["uncompressed_bytes"]),
            "uncompressed_sha256": str(row["uncompressed_sha256"]),
        }
        for row in rows
    ]
    stable.sort(key=lambda row: int(row["gid"]))
    return sha256_bytes(canonical_json(stable).encode("utf-8"))


def verify(
    tar_path: str,
    locator_db: str,
    container_name: str,
    payload_manifest: str | None = None,
) -> dict[str, object]:
    archive = Path(tar_path)
    connection = sqlite3.connect(f"file:{Path(locator_db).resolve()}?mode=ro", uri=True)
    try:
        container = connection.execute(
            "SELECT sha256, bytes, members FROM container WHERE container = ?",
            (container_name,),
        ).fetchone()
        errors: list[str] = []
        if container is None:
            raise ValueError(f"container not indexed: {container_name}")
        actual_tar_hash = sha256_file(archive)
        if actual_tar_hash != container[0]:
            errors.append("container SHA-256 mismatch")
        if archive.stat().st_size != int(container[1]):
            errors.append("container byte-size mismatch")

        expected_members: dict[int, dict[str, object]] = {}
        if payload_manifest:
            payload = json.loads(Path(payload_manifest).read_text(encoding="utf-8"))
            if payload.get("tar_sha256") != actual_tar_hash:
                errors.append("payload manifest tar SHA-256 mismatch")
            if int(payload.get("tar_bytes", -1)) != archive.stat().st_size:
                errors.append("payload manifest tar byte-size mismatch")
            raw_members = payload.get("members", [])
            if not isinstance(raw_members, list):
                errors.append("payload manifest members is not a list")
                raw_members = []
            for raw in raw_members:
                if not isinstance(raw, dict):
                    errors.append("payload manifest contains a non-object member")
                    continue
                gid = int(raw["gid"])
                if gid in expected_members:
                    errors.append(f"payload manifest duplicate gid {gid}")
                expected_members[gid] = raw
            if payload.get("logical_digest") != _logical_input_digest(
                list(expected_members.values())
            ):
                errors.append("payload manifest logical digest mismatch")

        rows = connection.execute(
            """SELECT gid, member, offset, length, encoding, payload_sha256
               FROM location WHERE container = ? AND route = 'local' ORDER BY gid""",
            (container_name,),
        ).fetchall()
        if len(rows) != int(container[2]):
            errors.append("locator member count differs from container record")
        locator_gids = {int(row[0]) for row in rows}
        if expected_members and locator_gids != set(expected_members):
            errors.append("payload manifest and locator cover different Gutenberg IDs")

        checked = 0
        with archive.open("rb") as raw_tar, tarfile.open(archive, "r:") as tar:
            tar_info = {info.name: info for info in tar if info.isfile()}
            for gid, member, offset, length, encoding, expected_hash in rows:
                gid = int(gid)
                info = tar_info.get(member)
                if info is None:
                    errors.append(f"gid {gid}: member missing from tar")
                    continue
                if info.offset_data != offset or info.size != length:
                    errors.append(f"gid {gid}: tar metadata offset/length mismatch")
                raw_tar.seek(offset)
                payload_bytes = raw_tar.read(length)
                actual_hash = sha256_bytes(payload_bytes)
                if actual_hash != expected_hash:
                    errors.append(f"gid {gid}: locator payload SHA-256 mismatch")
                expected = expected_members.get(gid)
                if expected:
                    if expected.get("member") != member:
                        errors.append(f"gid {gid}: manifest member name mismatch")
                    if int(expected.get("payload_bytes", -1)) != int(length):
                        errors.append(f"gid {gid}: manifest payload length mismatch")
                    if expected.get("payload_sha256") != actual_hash:
                        errors.append(f"gid {gid}: manifest payload SHA-256 mismatch")
                if encoding == "gzip":
                    try:
                        decoded = gzip.decompress(payload_bytes)
                    except OSError:
                        errors.append(f"gid {gid}: invalid gzip member")
                        continue
                    if expected:
                        if len(decoded) != int(expected.get("uncompressed_bytes", -1)):
                            errors.append(f"gid {gid}: uncompressed length mismatch")
                        if sha256_bytes(decoded) != expected.get("uncompressed_sha256"):
                            errors.append(f"gid {gid}: uncompressed SHA-256 mismatch")
                checked += 1
    finally:
        connection.close()

    return {
        "ok": not errors,
        "container": container_name,
        "checked": checked,
        "errors": errors,
        "tar_sha256": actual_tar_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tar", required=True)
    parser.add_argument("--locator-db", required=True)
    parser.add_argument("--container", default="gutenberg-payload")
    parser.add_argument("--payload-manifest")
    arguments = parser.parse_args()
    result = verify(
        arguments.tar,
        arguments.locator_db,
        arguments.container,
        arguments.payload_manifest,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
