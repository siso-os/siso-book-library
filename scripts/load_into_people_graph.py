#!/usr/bin/env python3
"""Safe compatibility entry point for the retired direct People Graph loader.

The old loader silently matched canonical entities by normalized name. This
command now writes ``pg-observation-0.1`` NDJSON instead. ``--graph`` is accepted
but never opened; ``--apply`` is rejected so automation fails closed rather than
mutating a canonical graph.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

from booklib.common import ContractError
from export_people_graph import export


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books", default="books.sqlite")
    parser.add_argument("--people", default="people.sqlite")
    parser.add_argument("--graph", help="deprecated; target is never opened")
    parser.add_argument("--output", default="book_people_observations.ndjson")
    parser.add_argument("--manifest")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    if args.apply:
        print(
            json.dumps(
                {
                    "error": "direct canonical mutation is retired",
                    "reason": "names are neither stable nor unique identifiers",
                    "safe_command": (
                        "python3 scripts/export_people_graph_observations.py "
                        "--books ... --contributors ... --out observations.ndjson"
                    ),
                    "graph_opened": False,
                    "graph_mutated": False,
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    try:
        result = export(
            args.books,
            args.people,
            args.output,
            manifest_path=args.manifest,
        )
    except (ContractError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    result.update(
        {
            "compatibility_entrypoint": "load_into_people_graph.py",
            "graph_argument_received": bool(args.graph),
            "graph_opened": False,
            "graph_mutated": False,
        }
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
