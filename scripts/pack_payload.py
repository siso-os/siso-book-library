#!/usr/bin/env python3
"""Pack individually gzipped books into deterministic uncompressed tar assets.

Each gzip stream has mtime=0 and no filename. Tar headers use fixed uid, gid,
mode, and mtime. The uncompressed tar container makes exact member byte ranges
addressable by local seek or HTTP Range. A successful run replaces the named
asset set and removes stale assets with the same prefix.
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from booklib.common import (
    ContractError,
    read_json,
    require_iso_utc,
    require_sha256,
    sha256_bytes,
    sha256_file,
    write_json,
)

PACKER_VERSION = "book-payload-packer/1.0.0"
PAYLOAD_RIGHTS_STATES = {
    "not_restricted_us",
    "restricted_or_permissioned",
    "pending",
    "public_domain_us",
}


def deterministic_gzip(payload: bytes, compresslevel: int = 9) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        compresslevel=compresslevel,
        fileobj=buffer,
        mtime=0,
    ) as handle:
        handle.write(payload)
    return buffer.getvalue()


def load_input_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("manifest_version") != "book-payload-input-1":
        raise ContractError("unsupported payload input manifest_version")
    for field in ("source_id", "snapshot_id", "retrieved_at", "rights_basis", "books"):
        if field not in manifest:
            raise ContractError(f"payload input manifest missing {field}")
    require_iso_utc(str(manifest["retrieved_at"]), "retrieved_at")
    if not isinstance(manifest["books"], list) or not manifest["books"]:
        raise ContractError("payload input manifest books must be a non-empty list")

    books: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in manifest["books"]:
        if not isinstance(item, dict):
            raise ContractError("payload book entries must be objects")
        for field in ("gid", "path", "source_uri", "rights_state"):
            if field not in item:
                raise ContractError(f"payload book entry missing {field}")
        gid = int(item["gid"])
        if gid in seen:
            raise ContractError(f"duplicate gid in payload input manifest: {gid}")
        seen.add(gid)
        if item["rights_state"] not in PAYLOAD_RIGHTS_STATES:
            raise ContractError(f"invalid payload rights_state for gid {gid}: {item['rights_state']}")
        source_path = (manifest_path.parent / str(item["path"])).resolve()
        if not source_path.is_file():
            raise ContractError(f"payload source file missing for gid {gid}: {source_path}")
        actual = sha256_file(source_path)
        expected = item.get("sha256")
        if expected:
            require_sha256(str(expected), f"books[{gid}].sha256")
            if expected != actual:
                raise ContractError(f"payload source digest mismatch for gid {gid}")
        books.append({**item, "gid": gid, "_path": source_path, "sha256": actual})
    return {
        **manifest,
        "books": sorted(books, key=lambda item: item["gid"]),
        "_manifest_path": manifest_path,
        "_manifest_sha256": sha256_file(manifest_path),
    }


def _write_asset(asset_path: Path, entries: list[dict[str, Any]]) -> None:
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(asset_path, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for entry in entries:
            raw_payload = Path(entry["_path"]).read_bytes()
            member_payload = deterministic_gzip(raw_payload)
            member_name = f"books/{entry['gid']}.txt.gz"
            info = tarfile.TarInfo(member_name)
            info.size = len(member_payload)
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(member_payload))


def _scan_asset(asset_path: Path, expected: dict[str, dict[str, Any]]) -> dict[str, Any]:
    members: list[dict[str, Any]] = []
    with tarfile.open(asset_path, mode="r:") as archive, asset_path.open("rb") as raw:
        for info in archive:
            if not info.isfile():
                continue
            if info.name not in expected:
                raise ContractError(f"unexpected payload member: {info.name}")
            raw.seek(info.offset_data)
            member_payload = raw.read(info.size)
            if len(member_payload) != info.size:
                raise ContractError(f"short range read for payload member: {info.name}")
            try:
                payload = gzip.decompress(member_payload)
            except (gzip.BadGzipFile, EOFError, OSError) as exc:
                raise ContractError(f"invalid gzip member: {info.name}") from exc
            source = expected[info.name]
            payload_sha = sha256_bytes(payload)
            if payload_sha != source["sha256"]:
                raise ContractError(f"payload digest mismatch after packing gid {source['gid']}")
            members.append(
                {
                    "gid": source["gid"],
                    "member": info.name,
                    "offset": info.offset_data,
                    "length": info.size,
                    "uncompressed_length": len(payload),
                    "payload_sha256": payload_sha,
                    "member_sha256": sha256_bytes(member_payload),
                    "source_path": source["path"],
                    "source_uri": source["source_uri"],
                    "rights_state": source["rights_state"],
                }
            )
    missing = sorted(set(expected) - {item["member"] for item in members})
    if missing:
        raise ContractError(f"payload asset missing members: {missing}")
    return {
        "asset": asset_path.name,
        "bytes": asset_path.stat().st_size,
        "sha256": sha256_file(asset_path),
        "member_count": len(members),
        "members": sorted(members, key=lambda item: item["gid"]),
    }


def pack(
    input_manifest_path: str | Path,
    out_dir: str | Path,
    *,
    asset_prefix: str = "gutenberg",
    max_members: int = 15000,
    manifest_out: str | Path | None = None,
) -> dict[str, Any]:
    if max_members <= 0:
        raise ContractError("max_members must be positive")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", asset_prefix):
        raise ContractError("asset_prefix may contain only letters, digits, dot, underscore, and dash")
    source = load_input_manifest(input_manifest_path)
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{asset_prefix}-stage-", dir=destination))
    try:
        assets: list[dict[str, Any]] = []
        books = source["books"]
        for start in range(0, len(books), max_members):
            sequence = start // max_members + 1
            chunk = books[start : start + max_members]
            asset_path = staging / f"{asset_prefix}-{sequence:03d}.tar"
            _write_asset(asset_path, chunk)
            expected = {f"books/{entry['gid']}.txt.gz": entry for entry in chunk}
            assets.append(_scan_asset(asset_path, expected))

        expected_names = {asset["asset"] for asset in assets}
        # Publish only after every staged asset has passed the scan.
        for asset in assets:
            os.replace(staging / asset["asset"], destination / asset["asset"])
        for existing in destination.glob(f"{asset_prefix}-*.tar"):
            if existing.name not in expected_names:
                existing.unlink()

        manifest = {
            "manifest_version": "book-payload-assets-1",
            "packer_version": PACKER_VERSION,
            "source_id": source["source_id"],
            "snapshot_id": source["snapshot_id"],
            "retrieved_at": source["retrieved_at"],
            "rights_basis": source["rights_basis"],
            "input_manifest_sha256": source["_manifest_sha256"],
            "format": {
                "container": "uncompressed_tar",
                "member": "gzip",
                "member_path": "books/{gid}.txt.gz",
                "gzip_mtime": 0,
                "tar_mtime": 0,
                "tar_uid": 0,
                "tar_gid": 0,
            },
            "asset_count": len(assets),
            "book_count": len(books),
            "assets": assets,
        }
        manifest_path = Path(manifest_out) if manifest_out else destination / "payload-manifest.json"
        write_json(manifest_path, manifest)
        return {
            "manifest": str(manifest_path),
            "manifest_sha256": sha256_file(manifest_path),
            "asset_count": len(assets),
            "book_count": len(books),
            "assets": [
                {key: asset[key] for key in ("asset", "bytes", "sha256", "member_count")}
                for asset in assets
            ],
        }
    finally:
        with contextlib.suppress(FileNotFoundError):
            shutil.rmtree(staging)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--asset-prefix", default="gutenberg")
    parser.add_argument("--max-members", type=int, default=15000)
    parser.add_argument("--manifest-out")
    args = parser.parse_args()
    try:
        summary = pack(
            args.input_manifest,
            args.out_dir,
            asset_prefix=args.asset_prefix,
            max_members=args.max_members,
            manifest_out=args.manifest_out,
        )
    except (ContractError, OSError, tarfile.TarError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
