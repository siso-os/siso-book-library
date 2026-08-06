#!/usr/bin/env python3
"""Combine component receipts into a versioned release manifest (no upload)."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    from scripts.common import (
        canonical_json,
        public_receipt,
        sha256_bytes,
        write_json_atomic,
    )
except ModuleNotFoundError:  # direct execution from scripts/
    from common import (  # type: ignore
        canonical_json,
        public_receipt,
        sha256_bytes,
        write_json_atomic,
    )


def create(
    component_paths: list[str],
    output_path: str,
    release_id: str,
    created_at: str | None = None,
) -> dict[str, object]:
    if not component_paths:
        raise ValueError("at least one component manifest is required")
    components: list[dict[str, object]] = []
    sources: dict[tuple[str, str], dict[str, object]] = {}
    for component_path in component_paths:
        path = Path(component_path)
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"component manifest is not an object: {path}")
        logical_digest = value.get("logical_digest")
        tar_digest = value.get("tar_sha256")
        if logical_digest is None and tar_digest is None:
            raise ValueError(
                f"component manifest has neither logical_digest nor tar_sha256: {path}"
            )
        component: dict[str, object] = {
            "path": path.name,
            "manifest_version": value.get("manifest_version"),
            "envelope_version": value.get("envelope_version"),
            "logical_digest": logical_digest,
            "tar_sha256": tar_digest,
            "row_counts": value.get("row_counts"),
            "loader_version": value.get("loader_version"),
            "schema_version": value.get("schema_version"),
        }
        # Hash only the public logical projection. Raw component files may be
        # formatted differently or contain runtime-only output locations; those
        # details must not change an aggregate release identity.
        component["component_receipt_sha256"] = sha256_bytes(
            canonical_json(public_receipt(component)).encode("utf-8")
        )
        components.append(component)
        source = value.get("source")
        if isinstance(source, dict):
            key = (str(source.get("source_id")), str(source.get("snapshot_id")))
            # Only public-safe source receipt fields are projected. Local paths
            # and credentials are never copied into the release manifest.
            projected = {
                field: source.get(field)
                for field in (
                    "source_id", "snapshot_id", "uri", "sha256", "retrieved_at",
                    "observed_at", "terms_revision", "rights_state", "rights_basis",
                    "acquisition_method", "logical_input_sha256",
                )
                if field in source and source.get(field) is not None
            }
            current = sources.setdefault(key, {})
            current.update(projected)
    created = created_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    body: dict[str, object] = {
        "manifest_version": "book-library-release-3",
        "release_id": release_id,
        "created_at": created,
        "publication_state": "manifest_only_no_assets_uploaded",
        "sources": [sources[key] for key in sorted(sources)],
        "components": sorted(components, key=lambda row: str(row["path"])),
        "rights_note": (
            "Metadata and text rights remain source- and jurisdiction-specific; "
            "this manifest does not expand reuse rights. Pending rights block upload."
        ),
        "binary_reproducibility": (
            "SQLite byte identity is not claimed; compare component logical digests, "
            "row counts, and source hashes. Payload tar byte identity is scoped to "
            "the recorded packer/toolchain contract."
        ),
    }
    body["manifest_sha256"] = sha256_bytes(canonical_json(body).encode("utf-8"))
    write_json_atomic(output_path, body)
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", action="append", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--created-at")
    arguments = parser.parse_args()
    print(json.dumps(create(
        arguments.component,
        arguments.out,
        arguments.release_id,
        arguments.created_at,
    ), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
