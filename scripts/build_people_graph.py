#!/usr/bin/env python3
"""Build source-local contributor observations without identity resolution.

Every row in ``source_contributor`` is one literal contributor occurrence on one
Project Gutenberg Work. Repeated labels share a comparison-only label hash, but
they are never collapsed into a person or organisation. This preserves roles,
order, aliases, pseudonyms, institutions, and Unicode while leaving canonical
identity to an evidence-based downstream review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

try:
    from scripts.common import (
        LOADER_VERSION,
        atomic_sqlite_target,
        canonical_json,
        logical_digest,
        table_counts,
        write_public_receipt_atomic,
    )
except ModuleNotFoundError:  # direct execution from scripts/
    from common import (  # type: ignore
        LOADER_VERSION,
        atomic_sqlite_target,
        canonical_json,
        logical_digest,
        table_counts,
        write_public_receipt_atomic,
    )

CONTRIBUTOR_SCHEMA_VERSION = "book-contributors-3"
SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE source_contributor (
  contributor_observation_id TEXT PRIMARY KEY,
  source_label_key TEXT NOT NULL,
  source_id TEXT NOT NULL,
  gid INTEGER NOT NULL,
  contribution_order INTEGER NOT NULL CHECK(contribution_order >= 1),
  source_label TEXT NOT NULL,
  display_name TEXT NOT NULL,
  birth_year INTEGER,
  death_year INTEGER,
  aliases_json TEXT NOT NULL,
  entity_kind_state TEXT NOT NULL CHECK(entity_kind_state IN ('unresolved','person','organisation')),
  classification_method TEXT NOT NULL,
  classification_evidence_json TEXT NOT NULL,
  raw_variants_json TEXT NOT NULL,
  UNIQUE (gid, contribution_order)
);
CREATE TABLE contribution (
  contributor_observation_id TEXT NOT NULL UNIQUE
    REFERENCES source_contributor(contributor_observation_id) ON DELETE CASCADE,
  gid INTEGER NOT NULL,
  role TEXT NOT NULL,
  contribution_order INTEGER NOT NULL CHECK(contribution_order >= 1),
  raw_label TEXT NOT NULL,
  PRIMARY KEY (gid, contribution_order)
);
CREATE INDEX ix_contributor_label_key ON source_contributor(source_label_key);
CREATE INDEX ix_contributor_display_name ON source_contributor(display_name);
CREATE INDEX ix_contribution_gid ON contribution(gid);
CREATE INDEX ix_contribution_role ON contribution(role);
CREATE TABLE source_manifest (
  source_id TEXT PRIMARY KEY,
  snapshot_id TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  terms_revision TEXT NOT NULL,
  rights_state TEXT NOT NULL,
  loader_version TEXT NOT NULL,
  schema_version TEXT NOT NULL
);
CREATE TABLE build_manifest (
  logical_digest TEXT PRIMARY KEY,
  row_counts_json TEXT NOT NULL,
  built_at TEXT NOT NULL,
  loader_version TEXT NOT NULL,
  schema_version TEXT NOT NULL
);
-- Comparison-only frequency. Equal labels are candidates for review, not identity.
CREATE VIEW source_label_frequency AS
SELECT source_label_key, MIN(source_label) AS example_label, COUNT(*) AS occurrences
FROM source_contributor
GROUP BY source_label_key;
-- Compatibility views expose old names but intentionally create one row per
-- contributor occurrence. `is_corporate` stays NULL and work_count stays 1.
CREATE VIEW person AS
SELECT contributor_observation_id AS person_key,
       display_name,
       display_name AS sort_name,
       birth_year,
       death_year,
       NULL AS is_corporate,
       raw_variants_json AS raw_variants,
       1 AS work_count
FROM source_contributor;
CREATE VIEW person_work AS
SELECT contributor_observation_id AS person_key, gid, role FROM contribution;
"""

ROLE = re.compile(r"\[([^\]]+)\]\s*$")
YEARS = re.compile(r",\s*(?:ca\.\s*)?(\d{3,4})\??\s*-\s*(\d{3,4})?\??\s*$")
OPEN_YEARS = re.compile(r",\s*([bd])\.\s*(\d{3,4})\??\s*$", re.IGNORECASE)
BCE_YEARS = re.compile(
    r",\s*(?:ca\.\s*)?(\d{1,4})\??\s*(?:BCE|B\.C\.?E?\.?)\s*-\s*"
    r"(\d{1,4})?\??\s*(?:BCE|B\.C\.?E?\.?)?\s*$",
    re.IGNORECASE,
)
PAREN_ALIAS = re.compile(r"\(([^()]*)\)")


def split_contributors(authors: str | None) -> list[str]:
    """Split the Gutenberg Authors field while preserving literal chunks."""

    return [part.strip() for part in (authors or "").split(";") if part.strip()]


def source_label_key(raw_label: str) -> str:
    """Comparison-only hash of an exact NFC label; never a canonical entity ID."""

    normalized = unicodedata.normalize("NFC", raw_label.strip())
    return "gutenberg-label:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def contributor_observation_id(gid: int, contribution_order: int) -> str:
    """Source-native occurrence ID, unique within a Project Gutenberg snapshot."""

    return f"gutenberg:work:{gid}:contributor:{contribution_order}"


def parse_contributor(raw_label: str) -> dict[str, object]:
    """Parse literal role/date/alias evidence without classifying identity."""

    raw = unicodedata.normalize("NFC", raw_label.strip())
    working = raw
    role = "author"
    role_match = ROLE.search(working)
    if role_match:
        role = role_match.group(1).strip().casefold().replace(" ", "_")
        working = working[: role_match.start()].rstrip()

    birth: int | None = None
    death: int | None = None
    bce = BCE_YEARS.search(working)
    if bce:
        birth = -int(bce.group(1))
        death = -int(bce.group(2)) if bce.group(2) else None
        working = working[: bce.start()].rstrip()
    else:
        years = YEARS.search(working)
        if years:
            birth = int(years.group(1))
            death = int(years.group(2)) if years.group(2) else None
            working = working[: years.start()].rstrip()
        else:
            open_year = OPEN_YEARS.search(working)
            if open_year:
                if open_year.group(1).casefold() == "b":
                    birth = int(open_year.group(2))
                else:
                    death = int(open_year.group(2))
                working = working[: open_year.start()].rstrip()

    aliases = [
        unicodedata.normalize("NFC", match.group(1).strip())
        for match in PAREN_ALIAS.finditer(working)
        if match.group(1).strip()
    ]
    display = working.strip().strip(",").strip() or raw
    return {
        "raw_label": raw,
        "display_name": display,
        "birth_year": birth,
        "death_year": death,
        "aliases": aliases,
        "role": role,
        # The catalog Authors field does not reliably distinguish humans from
        # institutions. No name-shape heuristic is promoted to source truth.
        "entity_kind_state": "unresolved",
        "classification_method": "source_field_unresolved",
        "classification_evidence": {
            "source_field": "Authors",
            "explicit_entity_kind": None,
            "note": "No name-shape heuristic promoted to an entity kind.",
        },
    }


def _source_metadata(books: sqlite3.Connection) -> tuple[object, ...]:
    try:
        row = books.execute(
            """SELECT source_id, snapshot_id, source_sha256, retrieved_at,
                      observed_at, terms_revision, rights_state
               FROM source_manifest LIMIT 1"""
        ).fetchone()
    except sqlite3.OperationalError as error:
        raise ValueError(
            "books database predates source manifests; rebuild it with "
            "scripts/build_books_module.py before exporting contributors"
        ) from error
    if row is None:
        raise ValueError("books database has no source_manifest row")
    return tuple(row)


def build(books_db: str, out_db: str, manifest_out: str | None = None) -> dict[str, object]:
    books = sqlite3.connect(f"file:{Path(books_db).resolve()}?mode=ro", uri=True)
    try:
        source_meta = _source_metadata(books)
        observations: list[tuple[object, ...]] = []
        contributions: list[tuple[object, ...]] = []
        for gid, authors in books.execute(
            """SELECT gid, authors FROM book
               WHERE authors IS NOT NULL AND trim(authors) != '' ORDER BY gid"""
        ):
            for order, chunk in enumerate(split_contributors(authors), start=1):
                parsed = parse_contributor(chunk)
                observation_id = contributor_observation_id(int(gid), order)
                label_key = source_label_key(str(parsed["raw_label"]))
                observations.append(
                    (
                        observation_id,
                        label_key,
                        source_meta[0],
                        int(gid),
                        order,
                        parsed["raw_label"],
                        parsed["display_name"],
                        parsed["birth_year"],
                        parsed["death_year"],
                        canonical_json(parsed["aliases"]),
                        parsed["entity_kind_state"],
                        parsed["classification_method"],
                        canonical_json(parsed["classification_evidence"]),
                        canonical_json([parsed["raw_label"]]),
                    )
                )
                contributions.append(
                    (
                        observation_id,
                        int(gid),
                        str(parsed["role"]),
                        order,
                        str(parsed["raw_label"]),
                    )
                )
    finally:
        books.close()

    with atomic_sqlite_target(out_db) as temporary:
        output = sqlite3.connect(temporary)
        try:
            output.executescript(SCHEMA)
            output.execute(
                "INSERT INTO source_manifest VALUES (?,?,?,?,?,?,?,?,?)",
                (*source_meta, LOADER_VERSION, CONTRIBUTOR_SCHEMA_VERSION),
            )
            output.executemany(
                "INSERT INTO source_contributor VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                observations,
            )
            output.executemany(
                "INSERT INTO contribution VALUES (?,?,?,?,?)", contributions
            )
            violations = output.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"foreign-key violations: {violations[:5]}")
            counts = table_counts(output, ("source_contributor", "contribution"))
            digest = logical_digest(
                output,
                (
                    (
                        "source_contributor",
                        (
                            "contributor_observation_id", "source_label_key",
                            "source_id", "gid", "contribution_order", "source_label",
                            "display_name", "birth_year", "death_year", "aliases_json",
                            "entity_kind_state", "classification_method",
                            "classification_evidence_json", "raw_variants_json",
                        ),
                    ),
                    (
                        "contribution",
                        (
                            "contributor_observation_id", "gid", "role",
                            "contribution_order", "raw_label",
                        ),
                    ),
                    (
                        "source_manifest",
                        (
                            "source_id", "snapshot_id", "source_sha256",
                            "terms_revision", "rights_state",
                        ),
                    ),
                ),
            )
            output.execute(
                "INSERT INTO build_manifest VALUES (?,?,?,?,?)",
                (
                    digest,
                    canonical_json(counts),
                    str(source_meta[3]),
                    LOADER_VERSION,
                    CONTRIBUTOR_SCHEMA_VERSION,
                ),
            )
            output.commit()
        finally:
            output.close()

    manifest: dict[str, object] = {
        "manifest_version": "book-library-contributors-2",
        "source": {
            "source_id": source_meta[0],
            "snapshot_id": source_meta[1],
            "sha256": source_meta[2],
            "retrieved_at": source_meta[3],
            "observed_at": source_meta[4],
            "terms_revision": source_meta[5],
            "rights_state": source_meta[6],
        },
        "loader_version": LOADER_VERSION,
        "schema_version": CONTRIBUTOR_SCHEMA_VERSION,
        "logical_digest": digest,
        "row_counts": counts,
        "identity_semantics": (
            "one contributor occurrence per Work/order; exact-label hash is "
            "comparison-only; no canonical or name-only merge"
        ),
        "database": out_db,
    }
    if manifest_out:
        write_public_receipt_atomic(manifest_out, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books", default="books.sqlite")
    parser.add_argument("--db", default="people.sqlite")
    parser.add_argument("--manifest-out")
    arguments = parser.parse_args()
    started = time.monotonic()
    summary = build(arguments.books, arguments.db, arguments.manifest_out)
    summary["elapsed_s"] = round(time.monotonic() - started, 3)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
