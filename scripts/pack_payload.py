#!/usr/bin/env python3
"""Pack deterministic, individually gzipped Gutenberg text members into a tar.

The tar itself remains uncompressed so the locator can expose exact byte ranges.
Each text is gzip-compressed independently with normalized metadata, and both
compressed and uncompressed SHA-256 values are recorded in the manifest.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import sys
import tarfile
import tempfile
import time
from pathlib import Path

try:
    from scripts.build_locator import build as build_locator, gid_from
    from scripts.common import (
        LOADER_VERSION,
        canonical_json,
        sha256_bytes,
        sha256_file,
        write_public_receipt_atomic,
    )
except ModuleNotFoundError:  # direct execution from scripts/
    from build_locator import build as build_locator, gid_from  # type: ignore
    from common import (  # type: ignore
        LOADER_VERSION,
        canonical_json,
        sha256_bytes,
        sha256_file,
        write_public_receipt_atomic,
    )

PACK_FORMAT_VERSION = "book-payload-pack-3"
ALLOWED_RIGHTS_STATES = {
    "public_metadata", "open_data", "restricted", "discovery_only", "pending"
}


def deterministic_gzip(data: bytes, level: int = 9) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(
        filename="", mode="wb", compresslevel=level, fileobj=output, mtime=0
    ) as compressor:
        compressor.write(data)
    return output.getvalue()


def _input_files(directory: Path) -> list[tuple[int, Path]]:
    rows: list[tuple[int, Path]] = []
    for path in sorted(directory.rglob("*.txt")):
        relative = path.relative_to(directory).as_posix()
        gid = gid_from(relative)
        if gid is None:
            gid = gid_from(path.name)
        if gid is None:
            raise ValueError(f"cannot derive Gutenberg ID from {relative}")
        rows.append((gid, path))
    gids = [gid for gid, _ in rows]
    if len(gids) != len(set(gids)):
        raise ValueError("input contains duplicate Gutenberg IDs")
    return sorted(rows)


def _logical_input_digest(members: list[dict[str, object]]) -> str:
    stable = [
        {
            "gid": row["gid"],
            "uncompressed_bytes": row["uncompressed_bytes"],
            "uncompressed_sha256": row["uncompressed_sha256"],
        }
        for row in members
    ]
    return sha256_bytes(canonical_json(stable).encode("utf-8"))


def pack(
    input_dir: str,
    tar_path: str,
    manifest_out: str,
    locator_db: str | None = None,
    locator_manifest_out: str | None = None,
    container_name: str = "gutenberg-payload",
    release_uri: str | None = None,
    compression_level: int = 9,
    source_id: str = "project_gutenberg_text",
    snapshot_id: str = "unknown",
    retrieved_at: str | None = None,
    terms_revision: str = "documented_unknown",
    rights_state: str = "pending",
    rights_basis: str = "not supplied; publication must remain blocked until reviewed",
) -> dict[str, object]:
    if rights_state not in ALLOWED_RIGHTS_STATES:
        raise ValueError(
            f"rights_state must be one of {sorted(ALLOWED_RIGHTS_STATES)}"
        )
    source = Path(input_dir)
    if not source.is_dir():
        raise NotADirectoryError(source)
    destination = Path(tar_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = _input_files(source)
    if not files:
        raise ValueError(f"no .txt payloads found under {source}")
    member_manifest: list[dict[str, object]] = []

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with tarfile.open(temporary, "w", format=tarfile.USTAR_FORMAT) as tar:
            for gid, path in files:
                raw = path.read_bytes()
                compressed = deterministic_gzip(raw, compression_level)
                member_name = f"books/{gid}.txt.gz"
                info = tarfile.TarInfo(member_name)
                info.size = len(compressed)
                info.mtime = 0
                info.mode = 0o644
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                tar.addfile(info, io.BytesIO(compressed))
                member_manifest.append({
                    "gid": gid,
                    "member": member_name,
                    "uncompressed_bytes": len(raw),
                    "uncompressed_sha256": sha256_bytes(raw),
                    "payload_bytes": len(compressed),
                    "payload_sha256": sha256_bytes(compressed),
                    "encoding": "gzip",
                })
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    retrieved = retrieved_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    logical_digest = _logical_input_digest(member_manifest)
    manifest: dict[str, object] = {
        "manifest_version": PACK_FORMAT_VERSION,
        "container": container_name,
        "format": "uncompressed_tar_of_individually_gzipped_members",
        "source": {
            "source_id": source_id,
            "snapshot_id": snapshot_id,
            "retrieved_at": retrieved,
            "terms_revision": terms_revision,
            "rights_state": rights_state,
            "rights_basis": rights_basis,
            "logical_input_sha256": logical_digest,
        },
        "determinism": {
            "gzip_mtime": 0,
            "gzip_filename": "",
            "tar_mtime": 0,
            "tar_uid_gid": 0,
            "tar_user_group_names": "empty",
            "member_order": "numeric_gutenberg_id",
            "claim": (
                "same inputs and compression toolchain yield the same tar; "
                "cross-zlib byte identity is not claimed"
            ),
        },
        "loader_version": LOADER_VERSION,
        "logical_digest": logical_digest,
        "row_counts": {"members": len(member_manifest)},
        "tar": str(destination),
        "tar_bytes": destination.stat().st_size,
        "tar_sha256": sha256_file(destination),
        "members": member_manifest,
    }
    write_public_receipt_atomic(manifest_out, manifest)
    if locator_db:
        locator = build_locator(
            tar_path=str(destination),
            db_path=locator_db,
            container_name=container_name,
            release_uri=release_uri,
            manifest_out=locator_manifest_out,
        )
        manifest["locator"] = locator
        write_public_receipt_atomic(manifest_out, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--tar", required=True)
    parser.add_argument("--manifest-out", required=True)
    parser.add_argument("--locator-db")
    parser.add_argument("--locator-manifest-out")
    parser.add_argument("--container", default="gutenberg-payload")
    parser.add_argument("--release-uri")
    parser.add_argument("--compression-level", type=int, default=9)
    parser.add_argument("--source-id", default="project_gutenberg_text")
    parser.add_argument("--snapshot-id", default="unknown")
    parser.add_argument("--retrieved-at")
    parser.add_argument("--terms-revision", default="documented_unknown")
    parser.add_argument("--rights-state", default="pending")
    parser.add_argument(
        "--rights-basis",
        default="not supplied; publication must remain blocked until reviewed",
    )
    arguments = parser.parse_args()
    print(json.dumps(pack(
        input_dir=arguments.input_dir,
        tar_path=arguments.tar,
        manifest_out=arguments.manifest_out,
        locator_db=arguments.locator_db,
        locator_manifest_out=arguments.locator_manifest_out,
        container_name=arguments.container,
        release_uri=arguments.release_uri,
        compression_level=arguments.compression_level,
        source_id=arguments.source_id,
        snapshot_id=arguments.snapshot_id,
        retrieved_at=arguments.retrieved_at,
        terms_revision=arguments.terms_revision,
        rights_state=arguments.rights_state,
        rights_basis=arguments.rights_basis,
    ), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
