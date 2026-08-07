#!/usr/bin/env python3
"""Compare two Book Library build summaries for logical equivalence.

SQLite files can differ at the byte/page level across platforms. This command
compares the declared logical receipts instead: metadata rows, contributor
observations, observation NDJSON, and deterministic payload manifests/assets.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class SummaryError(ValueError):
    """Raised when a build summary is missing a required receipt."""


def _read(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise SummaryError(f"summary must be a JSON object: {path}")
    return value


def _get(value: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = value
    for part in path:
        if not isinstance(current, dict) or part not in current:
            raise SummaryError(f"summary missing {'.'.join(path)}")
        current = current[part]
    return current


def comparable_receipts(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "books_logical_sha256": _get(summary, ("books", "logical_sha256")),
        "books_table_counts": _get(summary, ("books", "table_counts")),
        "contributors_logical_sha256": _get(
            summary, ("contributors", "logical_sha256")
        ),
        "contributors_table_counts": _get(
            summary, ("contributors", "table_counts")
        ),
        "observations_ndjson_sha256": _get(
            summary, ("observation_export", "ndjson_sha256")
        ),
        "observation_record_counts": _get(
            summary, ("observation_export", "subject_kind_counts")
        ),
        "payload_assets": _get(summary, ("payload", "assets")),
        "payload_manifest_sha256": _get(
            summary, ("payload", "manifest_sha256")
        ),
        "locator_logical_sha256": _get(
            summary, ("release", "locator_logical_sha256")
        ),
    }


def compare(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_receipts = comparable_receipts(left)
    right_receipts = comparable_receipts(right)
    mismatches = {
        name: {"left": left_receipts[name], "right": right_receipts[name]}
        for name in left_receipts
        if left_receipts[name] != right_receipts[name]
    }
    return {
        "equivalent": not mismatches,
        "authoritative_equivalence": "logical receipts and deterministic payload assets",
        "receipts": left_receipts if not mismatches else None,
        "mismatches": mismatches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left")
    parser.add_argument("right")
    args = parser.parse_args()
    try:
        result = compare(_read(args.left), _read(args.right))
    except (OSError, json.JSONDecodeError, SummaryError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["equivalent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
