#!/usr/bin/env python3
"""Print logical SQLite digests and row counts for reproducibility checks."""
from __future__ import annotations

import argparse
import json

from booklib.common import sqlite_logical_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", nargs="+")
    args = parser.parse_args()
    result = [
        {"database": database, **sqlite_logical_snapshot(database)}
        for database in args.database
    ]
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
