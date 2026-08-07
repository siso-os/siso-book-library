#!/usr/bin/env python3
"""Verify locator ranges, compression, lengths, and per-Work SHA-256 receipts."""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from booklib.common import ContractError, sha256_bytes, sha256_file, sqlite_readonly


def _asset_path(database: Path, stored_path: str, asset_root: str | Path | None) -> Path:
    candidate = Path(stored_path)
    if candidate.is_absolute():
        return candidate
    root = Path(asset_root).resolve() if asset_root else database.parent
    return (root / candidate).resolve()


def verify(
    db_path: str | Path,
    *,
    container_name: str | None = None,
    asset_root: str | Path | None = None,
    limit: int = 0,
) -> dict[str, Any]:
    database = Path(db_path).resolve()
    failures: list[dict[str, Any]] = []
    checked = 0
    by_container: dict[str, int] = {}
    with sqlite_readonly(database) as connection:
        query = "SELECT * FROM container"
        params: tuple[Any, ...] = ()
        if container_name:
            query += " WHERE container=?"
            params = (container_name,)
        query += " ORDER BY container"
        containers = connection.execute(query, params).fetchall()
        if not containers:
            raise ContractError("no matching containers in locator database")

        for container in containers:
            archive_path = _asset_path(database, container["stored_path"], asset_root)
            if not archive_path.is_file():
                failures.append(
                    {
                        "container": container["container"],
                        "error": "asset_missing",
                        "path": str(archive_path),
                    }
                )
                continue
            actual_container_sha = sha256_file(archive_path)
            if actual_container_sha != container["sha256"]:
                failures.append(
                    {
                        "container": container["container"],
                        "error": "container_sha256_mismatch",
                        "expected": container["sha256"],
                        "actual": actual_container_sha,
                    }
                )
                continue

            rows = connection.execute(
                "SELECT * FROM location WHERE container=? ORDER BY gid",
                (container["container"],),
            )
            with archive_path.open("rb") as archive:
                for row in rows:
                    if limit and checked >= limit:
                        break
                    checked += 1
                    by_container[container["container"]] = (
                        by_container.get(container["container"], 0) + 1
                    )
                    archive.seek(row["offset"])
                    member_payload = archive.read(row["length"])
                    if len(member_payload) != row["length"]:
                        failures.append(
                            {
                                "gid": row["gid"],
                                "container": row["container"],
                                "error": "short_range_read",
                                "expected": row["length"],
                                "actual": len(member_payload),
                            }
                        )
                        continue
                    member_sha = sha256_bytes(member_payload)
                    if member_sha != row["member_sha256"]:
                        failures.append(
                            {
                                "gid": row["gid"],
                                "container": row["container"],
                                "error": "member_sha256_mismatch",
                                "expected": row["member_sha256"],
                                "actual": member_sha,
                            }
                        )
                        continue
                    try:
                        content = (
                            gzip.decompress(member_payload)
                            if row["compression"] == "gzip"
                            else member_payload
                        )
                    except (gzip.BadGzipFile, EOFError, OSError) as exc:
                        failures.append(
                            {
                                "gid": row["gid"],
                                "container": row["container"],
                                "error": "decompression_failed",
                                "detail": str(exc),
                            }
                        )
                        continue
                    if len(content) != row["uncompressed_length"]:
                        failures.append(
                            {
                                "gid": row["gid"],
                                "container": row["container"],
                                "error": "uncompressed_length_mismatch",
                                "expected": row["uncompressed_length"],
                                "actual": len(content),
                            }
                        )
                    content_sha = sha256_bytes(content)
                    if content_sha != row["content_sha256"]:
                        failures.append(
                            {
                                "gid": row["gid"],
                                "container": row["container"],
                                "error": "content_sha256_mismatch",
                                "expected": row["content_sha256"],
                                "actual": content_sha,
                            }
                        )
            if limit and checked >= limit:
                break

    return {
        "database": str(database),
        "containers_checked": len(containers),
        "members_checked": checked,
        "members_by_container": dict(sorted(by_container.items())),
        "failures": failures,
        "valid": not failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="locator.sqlite")
    parser.add_argument("--container")
    parser.add_argument("--asset-root")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        result = verify(
            args.db,
            container_name=args.container,
            asset_root=args.asset_root,
            limit=args.limit,
        )
    except (ContractError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
