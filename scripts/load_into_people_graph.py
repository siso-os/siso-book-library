#!/usr/bin/env python3
"""Compatibility entry point for the Book Library People Graph handoff.

Canonical name-based writes were removed because they silently merged unrelated
people and promoted work counts into a universal rank. This command now exports
`pg-observation-0.1` records. A later identity-resolution lane may review them.
"""
from __future__ import annotations

import argparse
import json
import sys

try:
    from scripts.export_people_graph_observations import export
except ModuleNotFoundError:
    from export_people_graph_observations import export  # type: ignore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books", default="books.sqlite")
    parser.add_argument("--people", "--contributors", dest="contributors", default="people.sqlite")
    parser.add_argument("--out", default="book-library-observations.ndjson")
    # Retained only to produce an explicit, safe failure for old automation.
    parser.add_argument("--graph")
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    if arguments.apply or arguments.graph:
        parser.error(
            "canonical graph writes are no longer supported; export observations "
            "with --out and submit them to evidence-based identity review"
        )
    print(json.dumps(
        export(arguments.books, arguments.contributors, arguments.out),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
