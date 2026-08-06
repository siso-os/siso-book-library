#!/usr/bin/env python3
"""Build a source-replaceable Book Library metadata index.

Release builds use ``--source-manifest`` so snapshot identity, payload digest,
retrieval time, terms revision, rights basis, and row contract are explicit.
The database is built beside the destination and atomically replaces it only
when integrity and foreign-key checks pass. That makes a rerun true source
replacement: stale Works, fields, subjects, shelves, classes, and projections
cannot survive from an older snapshot.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from booklib import BOOK_INDEX_SCHEMA_VERSION, LOADER_VERSION
from booklib.common import (
    ContractError,
    atomic_database_path,
    canonical_json,
    load_source_manifest,
    nfc,
    require_iso_utc,
    sha256_file,
    sha256_text,
    sqlite_logical_snapshot,
)

LOC_SECTIONS = {
    "A": "General Works",
    "B": "Philosophy, Psychology, Religion",
    "C": "Auxiliary Sciences of History",
    "D": "World History",
    "E": "History of the Americas",
    "F": "Local History of the Americas",
    "G": "Geography, Anthropology, Recreation",
    "H": "Social Sciences",
    "J": "Political Science",
    "K": "Law",
    "L": "Education",
    "M": "Music",
    "N": "Fine Arts",
    "P": "Language and Literature",
    "Q": "Science",
    "R": "Medicine",
    "S": "Agriculture",
    "T": "Technology",
    "U": "Military Science",
    "V": "Naval Science",
    "Z": "Bibliography, Library Science",
}

SCHEMA = """
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=DELETE;
PRAGMA synchronous=FULL;
PRAGMA user_version=200;

CREATE TABLE source_snapshot (
  source_id            TEXT NOT NULL,
  snapshot_id          TEXT NOT NULL,
  source_uri           TEXT NOT NULL,
  source_observed_at   TEXT NOT NULL,
  retrieved_at         TEXT NOT NULL,
  terms_revision       TEXT NOT NULL,
  rights_state         TEXT NOT NULL,
  rights_basis         TEXT NOT NULL,
  acquisition_method   TEXT NOT NULL,
  payload_sha256       TEXT NOT NULL CHECK(length(payload_sha256) = 64),
  manifest_sha256      TEXT NOT NULL CHECK(length(manifest_sha256) = 64),
  raw_pointer_template TEXT NOT NULL,
  loader_version       TEXT NOT NULL,
  schema_version       TEXT NOT NULL,
  PRIMARY KEY (source_id, snapshot_id)
);

-- Historical column names stay available so existing read queries continue to
-- work. New provenance columns are additive.
CREATE TABLE book (
  gid                  INTEGER PRIMARY KEY,
  title                TEXT NOT NULL,
  authors              TEXT NOT NULL DEFAULT '',
  language             TEXT,
  issued               TEXT,
  media_type           TEXT,
  text_url             TEXT,
  rights               TEXT NOT NULL DEFAULT '',
  source               TEXT NOT NULL,
  fetched_at           TEXT NOT NULL,
  raw                  TEXT NOT NULL,
  payload_rights_state TEXT NOT NULL,
  snapshot_id          TEXT NOT NULL,
  observed_at          TEXT NOT NULL,
  raw_sha256           TEXT NOT NULL CHECK(length(raw_sha256) = 64),
  FOREIGN KEY (source, snapshot_id)
    REFERENCES source_snapshot(source_id, snapshot_id)
);

CREATE TABLE book_field (
  gid   INTEGER NOT NULL,
  field TEXT NOT NULL,
  value TEXT,
  PRIMARY KEY (gid, field),
  FOREIGN KEY (gid) REFERENCES book(gid) ON DELETE CASCADE
);
CREATE TABLE book_subject (
  gid     INTEGER NOT NULL,
  subject TEXT NOT NULL,
  PRIMARY KEY (gid, subject),
  FOREIGN KEY (gid) REFERENCES book(gid) ON DELETE CASCADE
);
CREATE TABLE book_shelf (
  gid   INTEGER NOT NULL,
  shelf TEXT NOT NULL,
  PRIMARY KEY (gid, shelf),
  FOREIGN KEY (gid) REFERENCES book(gid) ON DELETE CASCADE
);
CREATE TABLE book_class (
  gid          INTEGER NOT NULL,
  locc         TEXT NOT NULL,
  section      TEXT NOT NULL,
  bookcase     TEXT NOT NULL, -- compatibility name: alphabetic LCC subclass
  numeric_stem TEXT,
  PRIMARY KEY (gid, locc),
  FOREIGN KEY (gid) REFERENCES book(gid) ON DELETE CASCADE
);
CREATE TABLE subject_facet (
  subject TEXT NOT NULL,
  facet   TEXT NOT NULL,
  depth   INTEGER NOT NULL CHECK(depth >= 0),
  PRIMARY KEY (subject, depth)
);

CREATE INDEX ix_field       ON book_field(field);
CREATE INDEX ix_subject     ON book_subject(subject);
CREATE INDEX ix_shelf       ON book_shelf(shelf);
CREATE INDEX ix_section     ON book_class(section);
CREATE INDEX ix_subclass    ON book_class(bookcase);
CREATE INDEX ix_facet       ON subject_facet(facet);
CREATE INDEX ix_language    ON book(language);
CREATE INDEX ix_source_book ON book(source, snapshot_id);
"""

# LCC has a one-letter main class, an alphabetic subclass, then a number.
# Therefore D501 parses as section/subclass D + number 501, not subclass D5.
# PR6019 parses as section P + subclass PR + number 6019.
LCC_PREFIX = re.compile(r"^([A-Z])([A-Z]{0,2})(?=\d|\.|\s|$)")
LCC_NUMBER = re.compile(r"^[A-Z]{1,3}\s*(\d+(?:\.\d+)?)")


def split_multi(value: str | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for part in (value or "").split(";"):
        normalized = nfc(part.strip())
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result


def parse_locc(code: str | None) -> dict[str, str | None] | None:
    """Return normalized LCC components or ``None`` for an unusable value."""
    normalized = re.sub(r"\s+", "", nfc(code).upper())
    match = LCC_PREFIX.match(normalized)
    if not match or match.group(1) not in LOC_SECTIONS:
        return None
    section = match.group(1)
    subclass = section + match.group(2)
    number = LCC_NUMBER.match(normalized)
    return {
        "locc": normalized,
        "section": section,
        "subclass": subclass,
        "numeric_stem": number.group(1) if number else None,
    }


def observed_rights(row: dict[str, str | None]) -> str:
    for field in ("Rights", "Copyright Status", "Copyright"):
        value = nfc(row.get(field)).strip()
        if value:
            return value
    return ""


def classify_payload_rights(value: str | None) -> str:
    text = (value or "").casefold()
    if "public domain in the usa" in text or "not copyrighted in the united states" in text:
        return "not_restricted_us"
    if "copyright" in text or "permission" in text:
        return "restricted_or_permissioned"
    return "pending"


def _legacy_manifest(args: argparse.Namespace) -> dict[str, Any]:
    csv_path = Path(args.csv).resolve()
    if not csv_path.is_file():
        raise ContractError(f"catalog CSV does not exist: {csv_path}")
    if not args.retrieved_at:
        raise ContractError("legacy --csv mode requires --retrieved-at")
    require_iso_utc(args.retrieved_at, "retrieved_at")
    observed_at = args.source_observed_at or args.retrieved_at
    require_iso_utc(observed_at, "source_observed_at")
    payload_sha = sha256_file(csv_path)
    return {
        "manifest_version": "book-source-1",
        "source_id": args.source,
        "snapshot_id": args.snapshot_id or f"sha256:{payload_sha[:16]}",
        "source_uri": args.source_uri,
        "source_observed_at": observed_at,
        "retrieved_at": args.retrieved_at,
        "terms_revision": args.terms_revision,
        "rights_state": "public_metadata",
        "rights_basis": args.rights_basis,
        "acquisition_method": "legacy_cli",
        "payload_path": str(csv_path),
        "payload_sha256": payload_sha,
        "expected_row_contract": {
            "required_columns": ["Text#", "Title", "Authors", "Type", "LoCC"],
            "min_rows": 1,
        },
        "raw_pointer_template": f"{csv_path.name}#Text#={{gid}}",
        "_manifest_path": "legacy-cli",
        "_manifest_sha256": sha256_text("legacy-cli:" + str(csv_path)),
        "_payload_path": str(csv_path),
    }


def _insert_snapshot(connection: sqlite3.Connection, manifest: dict[str, Any]) -> None:
    connection.execute(
        "INSERT INTO source_snapshot VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            manifest["source_id"],
            manifest["snapshot_id"],
            manifest["source_uri"],
            manifest["source_observed_at"],
            manifest["retrieved_at"],
            manifest["terms_revision"],
            manifest["rights_state"],
            manifest["rights_basis"],
            manifest["acquisition_method"],
            manifest["payload_sha256"],
            manifest["_manifest_sha256"],
            manifest["raw_pointer_template"],
            LOADER_VERSION,
            BOOK_INDEX_SCHEMA_VERSION,
        ),
    )


def _build_database(
    csv_path: Path,
    output_path: Path,
    manifest: dict[str, Any],
    tier_sql_path: Path,
) -> dict[str, Any]:
    counts: dict[str, int] = {
        "rows_loaded": 0,
        "non_text_media_retained": 0,
        "book_field_rows": 0,
        "book_subject_edges": 0,
        "book_shelf_edges": 0,
        "book_class_edges": 0,
        "unparsed_lcc_values": 0,
    }
    facets: dict[str, list[str]] = {}
    with contextlib.closing(sqlite3.connect(output_path)) as connection:
        connection.executescript(SCHEMA)
        _insert_snapshot(connection, manifest)
        with open(csv_path, encoding="utf-8-sig", errors="strict", newline="") as handle:
            reader = csv.DictReader(handle)
            required = manifest["expected_row_contract"]["required_columns"]
            missing = sorted(set(required) - set(reader.fieldnames or []))
            if missing:
                raise ContractError(f"catalog missing required columns: {missing}")
            for row_number, row in enumerate(reader, start=2):
                raw_gid = (row.get("Text#") or "").strip()
                try:
                    gid = int(raw_gid)
                except ValueError as exc:
                    raise ContractError(f"row {row_number}: invalid Text# {raw_gid!r}") from exc

                normalized_row = {
                    str(field): nfc(value) if isinstance(value, str) else value
                    for field, value in row.items()
                    if field is not None
                }
                raw_json = canonical_json(normalized_row)
                media_type = nfc(row.get("Type")).strip()
                if media_type != "Text":
                    counts["non_text_media_retained"] += 1
                rights_literal = observed_rights(row)
                connection.execute(
                    """INSERT INTO book (
                         gid,title,authors,language,issued,media_type,text_url,rights,
                         source,fetched_at,raw,payload_rights_state,snapshot_id,
                         observed_at,raw_sha256
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        gid,
                        nfc(row.get("Title")).strip(),
                        nfc(row.get("Authors")).strip(),
                        nfc(row.get("Language")).strip(),
                        nfc(row.get("Issued")).strip(),
                        media_type,
                        f"https://www.gutenberg.org/ebooks/{gid}.txt.utf-8"
                        if media_type == "Text"
                        else None,
                        rights_literal,
                        manifest["source_id"],
                        manifest["retrieved_at"],
                        raw_json,
                        classify_payload_rights(rights_literal),
                        manifest["snapshot_id"],
                        manifest["source_observed_at"],
                        sha256_text(raw_json),
                    ),
                )
                counts["rows_loaded"] += 1

                for field, value in normalized_row.items():
                    connection.execute(
                        "INSERT INTO book_field(gid,field,value) VALUES (?,?,?)",
                        (gid, field, value),
                    )
                    counts["book_field_rows"] += 1

                for subject in split_multi(row.get("Subjects")):
                    connection.execute("INSERT INTO book_subject VALUES (?,?)", (gid, subject))
                    counts["book_subject_edges"] += 1
                    facets.setdefault(
                        subject,
                        [part.strip() for part in subject.split("--") if part.strip()],
                    )
                for shelf in split_multi(row.get("Bookshelves")):
                    connection.execute("INSERT INTO book_shelf VALUES (?,?)", (gid, shelf))
                    counts["book_shelf_edges"] += 1
                for raw_code in split_multi(row.get("LoCC")):
                    parsed = parse_locc(raw_code)
                    if parsed is None:
                        counts["unparsed_lcc_values"] += 1
                        continue
                    connection.execute(
                        "INSERT INTO book_class VALUES (?,?,?,?,?)",
                        (
                            gid,
                            parsed["locc"],
                            parsed["section"],
                            parsed["subclass"],
                            parsed["numeric_stem"],
                        ),
                    )
                    counts["book_class_edges"] += 1

        minimum = int(manifest["expected_row_contract"].get("min_rows", 0))
        maximum = manifest["expected_row_contract"].get("max_rows")
        if counts["rows_loaded"] < minimum:
            raise ContractError(
                f"catalog row contract failed: loaded {counts['rows_loaded']} but min_rows={minimum}"
            )
        if maximum is not None and counts["rows_loaded"] > int(maximum):
            raise ContractError(
                f"catalog row contract failed: loaded {counts['rows_loaded']} but max_rows={maximum}"
            )

        for subject in sorted(facets):
            for depth, facet in enumerate(facets[subject]):
                connection.execute(
                    "INSERT INTO subject_facet(subject,facet,depth) VALUES (?,?,?)",
                    (subject, facet, depth),
                )

        if not tier_sql_path.is_file():
            raise ContractError(f"tier SQL does not exist: {tier_sql_path}")
        connection.executescript(tier_sql_path.read_text(encoding="utf-8"))
        connection.commit()
        failures = connection.execute("PRAGMA foreign_key_check").fetchall()
        if failures:
            raise ContractError(f"foreign key violations: {failures[:5]}")
        queue_rows, queue_distinct = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT gid) FROM v_extraction_queue"
        ).fetchone()
        if queue_rows != queue_distinct:
            raise ContractError("v_extraction_queue must contain one row per Work")
        counts["extraction_queue_rows"] = queue_rows
        counts["distinct_lcc_subclasses"] = connection.execute(
            "SELECT COUNT(DISTINCT bookcase) FROM book_class"
        ).fetchone()[0]
        connection.execute("VACUUM")
    return counts


def build(
    manifest: dict[str, Any],
    db_path: str | Path,
    tier_sql_path: str | Path,
) -> dict[str, Any]:
    destination = Path(db_path)
    tier_sql = Path(tier_sql_path)
    with atomic_database_path(destination) as temporary:
        counts = _build_database(
            Path(manifest["_payload_path"]), temporary, manifest, tier_sql
        )
    return {
        **counts,
        "db": str(destination),
        "schema_version": BOOK_INDEX_SCHEMA_VERSION,
        "loader_version": LOADER_VERSION,
        "source_id": manifest["source_id"],
        "snapshot_id": manifest["snapshot_id"],
        "source_payload_sha256": manifest["payload_sha256"],
        **sqlite_logical_snapshot(destination),
    }


def default_tier_sql() -> Path:
    return Path(__file__).resolve().parents[1] / "index" / "tier_queries.sql"


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest")
    parser.add_argument("--csv", default="pg_catalog.csv")
    parser.add_argument("--db", default="books.sqlite")
    parser.add_argument("--tier-sql", default=str(default_tier_sql()))
    parser.add_argument("--source", default="project_gutenberg_catalog")
    parser.add_argument(
        "--source-uri",
        default="https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv",
    )
    parser.add_argument("--snapshot-id")
    parser.add_argument("--source-observed-at")
    parser.add_argument("--retrieved-at")
    parser.add_argument(
        "--terms-revision", default="https://www.gutenberg.org/policy/license"
    )
    parser.add_argument(
        "--rights-basis",
        default=(
            "Catalog metadata is recorded as public metadata; payload rights remain "
            "literal source observations requiring jurisdiction-aware review."
        ),
    )
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        manifest = (
            load_source_manifest(args.source_manifest)
            if args.source_manifest
            else _legacy_manifest(args)
        )
        summary = build(manifest, args.db, args.tier_sql)
    except (ContractError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
