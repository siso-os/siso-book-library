#!/usr/bin/env python3
"""Validate pg-observation-0.1 NDJSON without resolving identities."""
from __future__ import annotations

import argparse
import json
import sys

from booklib.common import ContractError
from export_people_graph_observations import validate_ndjson


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    args = parser.parse_args(argv)
    try:
        result = validate_ndjson(args.path)
    except (ContractError, OSError) as exc:
        result = {"file": args.path, "valid": False, "errors": [str(exc)]}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
