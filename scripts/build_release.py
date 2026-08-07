#!/usr/bin/env python3
"""Run the complete offline Book Library build, export, pack, verify, and receipt.

This command is suitable for tiny fixtures and full release inputs. It does not
upload assets. All outputs are written under ``--out-dir`` and can be deleted and
rebuilt from the two declared input manifests.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sqlite3
import sys
from pathlib import Path

from booklib.common import ContractError, load_source_manifest, read_json
from build_books_module import build as build_books, default_tier_sql
from build_locator import build as build_locator
from build_people_graph import build as build_contributors
from build_release_manifest import build_release_manifest
from export_people_graph_observations import export_records, write_ndjson
from pack_payload import load_input_manifest, pack
from verify_payload import verify


def _prune_locator(locator_db: Path, expected: set[str]) -> None:
    if not locator_db.exists():
        return
    with contextlib.closing(sqlite3.connect(locator_db)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        rows = [row[0] for row in connection.execute("SELECT container FROM container")]
        for container in rows:
            if container not in expected:
                connection.execute("DELETE FROM container WHERE container=?", (container,))
        connection.commit()


def build_release(
    *,
    source_manifest_path: str | Path,
    payload_input_manifest_path: str | Path,
    out_dir: str | Path,
    built_at: str,
    asset_prefix: str = "gutenberg",
    max_members: int = 15000,
    asset_base_uri: str = "release://payload/",
) -> dict[str, object]:
    source = load_source_manifest(source_manifest_path)
    payload_input = load_input_manifest(payload_input_manifest_path)
    if (source["source_id"], source["snapshot_id"]) != (
        payload_input["source_id"],
        payload_input["snapshot_id"],
    ):
        raise ContractError("metadata and payload input manifests describe different snapshots")

    root = Path(out_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    payload_dir = root / "payload"
    books_db = root / "books.sqlite"
    contributors_db = root / "contributors.sqlite"
    observations = root / "people-graph-observations.ndjson"
    locator_db = root / "locator.sqlite"
    release_manifest = root / "release-manifest.json"

    books_result = build_books(source, books_db, default_tier_sql())
    contributors_result = build_contributors(books_db, contributors_db)
    export_result = write_ndjson(
        export_records(books_db, contributors_db), observations
    )
    pack_result = pack(
        payload_input_manifest_path,
        payload_dir,
        asset_prefix=asset_prefix,
        max_members=max_members,
    )
    payload_manifest_path = Path(pack_result["manifest"])
    payload_manifest = read_json(payload_manifest_path)
    expected_containers: set[str] = set()
    locator_results: list[dict[str, object]] = []
    for asset in payload_manifest["assets"]:
        asset_name = asset["asset"]
        expected_containers.add(asset_name)
        locator_results.append(
            build_locator(
                payload_dir / asset_name,
                locator_db,
                container_name=asset_name,
                stored_path=f"payload/{asset_name}",
                uri=asset_base_uri.rstrip("/") + "/" + asset_name,
                indexed_at=built_at,
                route="release",
            )
        )
    _prune_locator(locator_db, expected_containers)
    verification = verify(locator_db, asset_root=root)
    if not verification["valid"]:
        raise ContractError(f"payload verification failed: {verification['failures'][:3]}")
    release_result = build_release_manifest(
        source_manifest_path=source_manifest_path,
        books_db=books_db,
        contributors_db=contributors_db,
        observations_path=observations,
        output_path=release_manifest,
        built_at=built_at,
        payload_manifest_path=payload_manifest_path,
        payload_root=payload_dir,
        locator_db=locator_db,
        locator_asset_root=root,
    )
    return {
        "out_dir": str(root),
        "books": books_result,
        "contributors": contributors_result,
        "observation_export": export_result,
        "payload": pack_result,
        "locator_containers": locator_results,
        "payload_verification": verification,
        "release": release_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--payload-input-manifest", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--built-at", required=True)
    parser.add_argument("--asset-prefix", default="gutenberg")
    parser.add_argument("--max-members", type=int, default=15000)
    parser.add_argument("--asset-base-uri", default="release://payload/")
    args = parser.parse_args()
    try:
        result = build_release(
            source_manifest_path=args.source_manifest,
            payload_input_manifest_path=args.payload_input_manifest,
            out_dir=args.out_dir,
            built_at=args.built_at,
            asset_prefix=args.asset_prefix,
            max_members=args.max_members,
            asset_base_uri=args.asset_base_uri,
        )
    except (ContractError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
