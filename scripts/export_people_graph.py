#!/usr/bin/env python3
"""Compatibility wrapper for the versioned Book Library observation exporter.

New automation should call ``export_people_graph_observations.py``. This file
keeps the shorter historical command name and accepts ``--people`` as an alias
for the contributor-observation database.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from booklib.common import ContractError, sha256_file, write_json
from export_people_graph_observations import export_records, write_ndjson


def export(
    books_db: str,
    contributors_db: str,
    output_path: str,
    *,
    manifest_path: str | None = None,
) -> dict[str, Any]:
    result = write_ndjson(export_records(books_db, contributors_db), output_path)
    result.update(
        {
            "contract": "pg-observation-0.1",
            "canonical_identity_assigned": False,
            "name_only_merge_performed": False,
        }
    )
    if manifest_path:
        manifest = {
            "manifest_version": "book-people-export-1",
            "contract": "pg-observation-0.1",
            "output_file": Path(output_path).name,
            "output_sha256": sha256_file(output_path),
            "records": result["records"],
            "subject_kind_counts": result["subject_kind_counts"],
            "canonical_identity_assigned": False,
            "name_only_merge_performed": False,
        }
        write_json(manifest_path, manifest)
        result["manifest"] = manifest_path
        result["manifest_sha256"] = sha256_file(manifest_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books", required=True)
    parser.add_argument("--contributors")
    parser.add_argument("--people", help="compatibility alias for --contributors")
    parser.add_argument("--out")
    parser.add_argument("--output", help="compatibility alias for --out")
    parser.add_argument("--manifest")
    args = parser.parse_args()
    contributors = args.contributors or args.people
    output = args.out or args.output
    if not contributors or not output:
        parser.error("--contributors/--people and --out/--output are required")
    try:
        result = export(args.books, contributors, output, manifest_path=args.manifest)
    except (ContractError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
