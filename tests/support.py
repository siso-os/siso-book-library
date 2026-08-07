from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from booklib.common import load_source_manifest  # noqa: E402
from build_books_module import build as build_books, default_tier_sql  # noqa: E402
from build_people_graph import build as build_contributors  # noqa: E402

CATALOG_V1 = ROOT / "manifests" / "fixtures" / "catalog-v1.json"
CATALOG_V2 = ROOT / "manifests" / "fixtures" / "catalog-v2.json"
PAYLOAD_V1 = ROOT / "manifests" / "fixtures" / "payload-v1.json"
PAYLOAD_V2 = ROOT / "manifests" / "fixtures" / "payload-v2.json"
FIXED_TIME_V1 = "2026-08-06T00:10:00Z"
FIXED_TIME_V2 = "2026-08-06T01:10:00Z"


def build_pair(root: Path, catalog: Path = CATALOG_V1) -> tuple[Path, Path, dict, dict]:
    books = root / "books.sqlite"
    contributors = root / "contributors.sqlite"
    manifest = load_source_manifest(catalog)
    books_result = build_books(manifest, books, default_tier_sql())
    contributors_result = build_contributors(books, contributors)
    return books, contributors, books_result, contributors_result


def read_ndjson(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_keys(child)


def walk_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_strings(child)
