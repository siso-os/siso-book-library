#!/usr/bin/env python3
"""Create a public-safe release receipt for Book Library build artifacts.

The receipt records source/snapshot identity, source and artifact hashes, logical
SQLite digests, row counts, rights coverage, observation validation, payload
asset checksums, and locator verification. Local absolute paths are never copied
into the release manifest.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from booklib import (
    BOOK_INDEX_SCHEMA_VERSION,
    CONTRIBUTOR_GRAPH_SCHEMA_VERSION,
    LOADER_VERSION,
    OBSERVATION_ENVELOPE_VERSION,
)
from booklib.common import (
    ContractError,
    load_source_manifest,
    read_json,
    require_iso_utc,
    sha256_file,
    sqlite_logical_snapshot,
    sqlite_readonly,
    write_json,
)
from build_locator import LOCATOR_SCHEMA_VERSION, locator_logical_snapshot
from export_people_graph_observations import validate_ndjson
from verify_payload import verify as verify_payload

RELEASE_MANIFEST_VERSION = "book-library-release-1"


def _artifact_receipt(path: str | Path, logical: dict[str, Any]) -> dict[str, Any]:
    source = Path(path)
    return {
        "file": source.name,
        "bytes": source.stat().st_size,
        **logical,
    }


def _rights_counts(books_db: str | Path) -> dict[str, int]:
    with sqlite_readonly(books_db) as connection:
        return {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT payload_rights_state, COUNT(*) FROM book "
                "GROUP BY payload_rights_state ORDER BY payload_rights_state"
            )
        }


def _source_identity(db_path: str | Path) -> tuple[str, str]:
    with sqlite_readonly(db_path) as connection:
        row = connection.execute(
            "SELECT source_id,snapshot_id FROM source_snapshot"
        ).fetchone()
        if row is None:
            raise ContractError(f"source_snapshot missing from {db_path}")
        return row[0], row[1]


def _payload_receipt(
    payload_manifest_path: str | Path,
    payload_root: str | Path | None,
) -> dict[str, Any]:
    manifest_path = Path(payload_manifest_path).resolve()
    manifest = read_json(manifest_path)
    if manifest.get("manifest_version") != "book-payload-assets-1":
        raise ContractError("unsupported payload asset manifest")
    root = Path(payload_root).resolve() if payload_root else manifest_path.parent
    assets: list[dict[str, Any]] = []
    for asset in manifest.get("assets", []):
        path = root / asset["asset"]
        if not path.is_file():
            raise ContractError(f"payload asset missing: {path}")
        actual = sha256_file(path)
        if actual != asset["sha256"]:
            raise ContractError(f"payload asset digest mismatch: {asset['asset']}")
        assets.append(
            {
                "file": asset["asset"],
                "bytes": asset["bytes"],
                "sha256": asset["sha256"],
                "member_count": asset["member_count"],
            }
        )
    return {
        "manifest_file": manifest_path.name,
        "manifest_sha256": sha256_file(manifest_path),
        "format": manifest["format"],
        "asset_count": manifest["asset_count"],
        "book_count": manifest["book_count"],
        "assets": assets,
    }


def build_release_manifest(
    *,
    source_manifest_path: str | Path,
    books_db: str | Path,
    contributors_db: str | Path,
    observations_path: str | Path,
    output_path: str | Path,
    built_at: str,
    payload_manifest_path: str | Path | None = None,
    payload_root: str | Path | None = None,
    locator_db: str | Path | None = None,
    locator_asset_root: str | Path | None = None,
) -> dict[str, Any]:
    require_iso_utc(built_at, "built_at")
    source = load_source_manifest(source_manifest_path)
    expected_identity = (source["source_id"], source["snapshot_id"])
    if _source_identity(books_db) != expected_identity:
        raise ContractError("books database source identity does not match manifest")
    if _source_identity(contributors_db) != expected_identity:
        raise ContractError("contributors database source identity does not match manifest")

    observation_receipt = validate_ndjson(observations_path)
    components: dict[str, Any] = {
        "books_index": _artifact_receipt(
            books_db, sqlite_logical_snapshot(books_db)
        ),
        "contributor_observations": _artifact_receipt(
            contributors_db, sqlite_logical_snapshot(contributors_db)
        ),
        "people_graph_observations": {
            "file": Path(observations_path).name,
            "bytes": Path(observations_path).stat().st_size,
            "records": observation_receipt["records"],
            "subject_kind_counts": observation_receipt["subject_kind_counts"],
            "ndjson_sha256": observation_receipt["ndjson_sha256"],
            "valid": observation_receipt["valid"],
        },
    }

    if payload_manifest_path:
        components["payload"] = _payload_receipt(payload_manifest_path, payload_root)
    if locator_db:
        verification = verify_payload(locator_db, asset_root=locator_asset_root)
        if not verification["valid"]:
            raise ContractError(f"payload verification failed: {verification['failures'][:3]}")
        components["locator"] = {
            **_artifact_receipt(locator_db, locator_logical_snapshot(locator_db)),
            "verification": {
                "valid": True,
                "containers_checked": verification["containers_checked"],
                "members_checked": verification["members_checked"],
            },
        }

    release = {
        "manifest_version": RELEASE_MANIFEST_VERSION,
        "built_at": built_at,
        "loader_version": LOADER_VERSION,
        "contracts": {
            "books_index": BOOK_INDEX_SCHEMA_VERSION,
            "contributors": CONTRIBUTOR_GRAPH_SCHEMA_VERSION,
            "people_graph_export": OBSERVATION_ENVELOPE_VERSION,
            "locator": LOCATOR_SCHEMA_VERSION if locator_db else None,
            "reproducibility_authority": "logical_sha256",
        },
        "source": {
            "source_id": source["source_id"],
            "snapshot_id": source["snapshot_id"],
            "source_uri": source["source_uri"],
            "source_observed_at": source["source_observed_at"],
            "retrieved_at": source["retrieved_at"],
            "terms_revision": source["terms_revision"],
            "rights_state": source["rights_state"],
            "rights_basis": source["rights_basis"],
            "payload_sha256": source["payload_sha256"],
            "source_manifest_file": Path(source_manifest_path).name,
            "source_manifest_sha256": source["_manifest_sha256"],
        },
        "rights_coverage": _rights_counts(books_db),
        "components": components,
        "claims": {
            "byte_for_byte_sqlite_reproducibility": False,
            "logical_reproducibility_measured": True,
            "canonical_people_graph_ids_assigned": False,
            "name_only_identity_merges": False,
            "large_assets_uploaded": False,
        },
    }
    write_json(output_path, release)
    result = {
        "manifest": str(output_path),
        "manifest_sha256": sha256_file(output_path),
        "source_id": source["source_id"],
        "snapshot_id": source["snapshot_id"],
        "component_count": len(components),
        "rights_coverage": release["rights_coverage"],
    }
    if "locator" in components:
        result["locator_logical_sha256"] = components["locator"]["logical_sha256"]
    if "payload" in components:
        result["payload_manifest_sha256"] = components["payload"]["manifest_sha256"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--books", required=True)
    parser.add_argument("--contributors", required=True)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--built-at", required=True)
    parser.add_argument("--payload-manifest")
    parser.add_argument("--payload-root")
    parser.add_argument("--locator")
    parser.add_argument("--locator-asset-root")
    args = parser.parse_args()
    try:
        result = build_release_manifest(
            source_manifest_path=args.source_manifest,
            books_db=args.books,
            contributors_db=args.contributors,
            observations_path=args.observations,
            output_path=args.out,
            built_at=args.built_at,
            payload_manifest_path=args.payload_manifest,
            payload_root=args.payload_root,
            locator_db=args.locator,
            locator_asset_root=args.locator_asset_root,
        )
    except (ContractError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
