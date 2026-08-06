#!/usr/bin/env python3
"""Build a source-replaceable Project Gutenberg metadata index.

The destination is rebuilt in a sibling temporary file and atomically replaced.
That makes a rerun a full source replacement: books and all dependent subjects,
shelves, classes, fields, facets, and queue inputs removed upstream disappear.

Usage:
  python3 scripts/build_books_module.py --csv pg_catalog.csv --db books.sqlite \
      --snapshot-id pg-2026-08-06 --retrieved-at 2026-08-06T00:00:00Z \
      --terms-revision https://www.gutenberg.org/policy/permission.html
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

try:
    from scripts.common import (
        LOADER_VERSION,
        SCHEMA_VERSION,
        atomic_sqlite_target,
        canonical_json,
        logical_digest,
        sha256_file,
        table_counts,
        write_public_receipt_atomic,
    )
except ModuleNotFoundError:  # direct execution from scripts/
    from common import (  # type: ignore
        LOADER_VERSION,
        SCHEMA_VERSION,
        atomic_sqlite_target,
        canonical_json,
        logical_digest,
        sha256_file,
        table_counts,
        write_public_receipt_atomic,
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
PRAGMA foreign_keys = ON;
CREATE TABLE source_manifest (
  source_id TEXT PRIMARY KEY,
  snapshot_id TEXT NOT NULL,
  source_uri TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  terms_revision TEXT NOT NULL,
  rights_state TEXT NOT NULL,
  rights_basis TEXT NOT NULL,
  acquisition_method TEXT NOT NULL,
  loader_version TEXT NOT NULL,
  schema_version TEXT NOT NULL
);
CREATE TABLE book (
  gid INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  authors TEXT,
  language TEXT,
  issued TEXT,
  media_type TEXT,
  text_url TEXT,
  rights TEXT NOT NULL,
  source TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  raw TEXT NOT NULL
);
CREATE TABLE book_field (
  gid INTEGER NOT NULL REFERENCES book(gid) ON DELETE CASCADE,
  field TEXT NOT NULL,
  value TEXT,
  PRIMARY KEY (gid, field)
);
CREATE TABLE book_subject (
  gid INTEGER NOT NULL REFERENCES book(gid) ON DELETE CASCADE,
  subject TEXT NOT NULL,
  PRIMARY KEY (gid, subject)
);
CREATE TABLE book_shelf (
  gid INTEGER NOT NULL REFERENCES book(gid) ON DELETE CASCADE,
  shelf TEXT NOT NULL,
  PRIMARY KEY (gid, shelf)
);
CREATE TABLE book_class (
  gid INTEGER NOT NULL REFERENCES book(gid) ON DELETE CASCADE,
  locc TEXT NOT NULL,
  section TEXT NOT NULL,
  section_name TEXT NOT NULL,
  bookcase TEXT NOT NULL,
  PRIMARY KEY (gid, locc)
);
CREATE TABLE subject_facet (
  subject TEXT NOT NULL,
  facet TEXT NOT NULL,
  depth INTEGER NOT NULL CHECK(depth >= 0),
  PRIMARY KEY (subject, depth)
);
CREATE TABLE build_manifest (
  build_id TEXT PRIMARY KEY,
  logical_digest TEXT NOT NULL,
  row_counts_json TEXT NOT NULL,
  built_at TEXT NOT NULL,
  loader_version TEXT NOT NULL,
  schema_version TEXT NOT NULL
);
CREATE INDEX ix_field ON book_field(field);
CREATE INDEX ix_subject ON book_subject(subject);
CREATE INDEX ix_shelf ON book_shelf(shelf);
CREATE INDEX ix_section ON book_class(section);
CREATE INDEX ix_bookcase ON book_class(bookcase);
CREATE INDEX ix_facet ON subject_facet(facet);
CREATE INDEX ix_lang ON book(language);
"""

DIGEST_TABLES = (
    ("source_manifest", (
        "source_id", "snapshot_id", "source_uri", "source_sha256",
        "terms_revision", "rights_state", "rights_basis",
        "acquisition_method",
    )),
    ("book", (
        "gid", "title", "authors", "language", "issued", "media_type",
        "text_url", "rights", "source", "raw",
    )),
    ("book_field", ("gid", "field", "value")),
    ("book_subject", ("gid", "subject")),
    ("book_shelf", ("gid", "shelf")),
    ("book_class", ("gid", "locc", "section", "section_name", "bookcase")),
    ("subject_facet", ("subject", "facet", "depth")),
)
ALLOWED_RIGHTS_STATES = {
    "public_metadata", "open_data", "restricted", "discovery_only", "pending"
}

DATA_TABLES = (
    "book", "book_field", "book_subject", "book_shelf", "book_class",
    "subject_facet",
)


def split_multi(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(";") if part.strip()]


def parse_locc(code: str | None) -> tuple[str, str] | None:
    """Return top-level section and subclass/bookcase.

    The subclass is the initial letter plus the next letter *or digit*:
    ``PR`` -> ``("P", "PR")`` and ``D501`` -> ``("D", "D5")``.
    """

    normalized = re.sub(r"\s+", "", (code or "").strip().upper())
    match = re.match(r"^([A-Z])([A-Z0-9]?)", normalized)
    if not match or match.group(1) not in LOC_SECTIONS:
        return None
    section = match.group(1)
    second = match.group(2)
    return section, section + second if second else section


def _install_tier_views(connection: sqlite3.Connection, tier_sql: Path | None) -> None:
    if tier_sql is None:
        return
    connection.executescript(tier_sql.read_text(encoding="utf-8"))


def build(
    csv_path: str,
    db_path: str,
    rights: str = "public_metadata",
    source_id: str = "project_gutenberg",
    snapshot_id: str = "unknown",
    source_uri: str = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv",
    retrieved_at: str | None = None,
    observed_at: str | None = None,
    terms_revision: str = "documented_unknown",
    rights_basis: str = "Project Gutenberg catalog metadata; jurisdiction-specific text rights",
    acquisition_method: str = "user_supplied_snapshot",
    tier_sql: str | None = None,
    manifest_out: str | None = None,
) -> dict[str, object]:
    csv_file = Path(csv_path)
    if not csv_file.is_file():
        raise FileNotFoundError(csv_file)
    if rights not in ALLOWED_RIGHTS_STATES:
        raise ValueError(
            f"rights must be one of {sorted(ALLOWED_RIGHTS_STATES)}; got {rights!r}. "
            "Record jurisdiction-specific text rights in rights_basis instead."
        )
    retrieved = retrieved_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    observed = observed_at or retrieved
    source_digest = sha256_file(csv_file)
    resolved_tier_sql = (
        Path(tier_sql)
        if tier_sql
        else Path(__file__).resolve().parents[1] / "index" / "tier_queries.sql"
    )
    if not resolved_tier_sql.exists():
        raise FileNotFoundError(
            f"extraction queue SQL not found: {resolved_tier_sql}"
        )

    with atomic_sqlite_target(db_path) as temporary:
        connection = sqlite3.connect(temporary)
        try:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT INTO source_manifest VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    source_id,
                    snapshot_id,
                    source_uri,
                    source_digest,
                    retrieved,
                    observed,
                    terms_revision,
                    rights,
                    rights_basis,
                    acquisition_method,
                    LOADER_VERSION,
                    SCHEMA_VERSION,
                ),
            )
            facets: dict[str, list[str]] = {}
            with csv_file.open(encoding="utf-8-sig", errors="strict", newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames or "Text#" not in reader.fieldnames:
                    raise ValueError("catalog CSV must contain a Text# column")
                seen_gids: set[int] = set()
                for row_number, row in enumerate(reader, start=2):
                    if None in row:
                        raise ValueError(
                            f"malformed CSV row {row_number}: more values than headers"
                        )
                    raw_gid = (row.get("Text#") or "").strip()
                    if not raw_gid:
                        continue
                    try:
                        gid = int(raw_gid)
                    except ValueError as error:
                        raise ValueError(f"invalid Text# at CSV row {row_number}: {raw_gid!r}") from error
                    if gid in seen_gids:
                        raise ValueError(f"duplicate Text# at CSV row {row_number}: {gid}")
                    seen_gids.add(gid)
                    media_type = (row.get("Type") or "").strip()
                    canonical_raw = canonical_json(row)
                    connection.execute(
                        "INSERT INTO book VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            gid,
                            (row.get("Title") or "").strip(),
                            (row.get("Authors") or "").strip(),
                            (row.get("Language") or "").strip(),
                            (row.get("Issued") or "").strip(),
                            media_type,
                            f"https://www.gutenberg.org/ebooks/{gid}.txt.utf-8"
                            if media_type == "Text"
                            else None,
                            rights,
                            source_id,
                            retrieved,
                            canonical_raw,
                        ),
                    )
                    connection.executemany(
                        "INSERT INTO book_field VALUES (?,?,?)",
                        ((gid, field, value) for field, value in row.items() if field is not None),
                    )
                    for subject in split_multi(row.get("Subjects")):
                        connection.execute(
                            "INSERT OR IGNORE INTO book_subject VALUES (?,?)",
                            (gid, subject),
                        )
                        facets.setdefault(
                            subject,
                            [piece.strip() for piece in subject.split("--") if piece.strip()],
                        )
                    for shelf in split_multi(row.get("Bookshelves")):
                        connection.execute(
                            "INSERT OR IGNORE INTO book_shelf VALUES (?,?)", (gid, shelf)
                        )
                    for raw_code in split_multi(row.get("LoCC")):
                        parsed = parse_locc(raw_code)
                        if parsed is None:
                            continue
                        section, bookcase = parsed
                        normalized_code = re.sub(r"\s+", "", raw_code.strip().upper())
                        connection.execute(
                            "INSERT OR IGNORE INTO book_class VALUES (?,?,?,?,?)",
                            (
                                gid,
                                normalized_code,
                                section,
                                LOC_SECTIONS[section],
                                bookcase,
                            ),
                        )
            for subject, pieces in sorted(facets.items()):
                connection.executemany(
                    "INSERT INTO subject_facet VALUES (?,?,?)",
                    ((subject, facet, depth) for depth, facet in enumerate(pieces)),
                )
            _install_tier_views(connection, resolved_tier_sql)
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"foreign-key violations: {violations[:5]}")
            counts = table_counts(connection, DATA_TABLES)
            digest = logical_digest(connection, DIGEST_TABLES)
            build_id = f"{source_id}:{snapshot_id}:{source_digest[:12]}"
            connection.execute(
                "INSERT INTO build_manifest VALUES (?,?,?,?,?,?)",
                (
                    build_id,
                    digest,
                    canonical_json(counts),
                    retrieved,
                    LOADER_VERSION,
                    SCHEMA_VERSION,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    manifest: dict[str, object] = {
        "manifest_version": "book-library-build-1",
        "build_id": build_id,
        "source": {
            "source_id": source_id,
            "snapshot_id": snapshot_id,
            "uri": source_uri,
            "sha256": source_digest,
            "retrieved_at": retrieved,
            "observed_at": observed,
            "terms_revision": terms_revision,
            "rights_state": rights,
            "rights_basis": rights_basis,
            "acquisition_method": acquisition_method,
        },
        "loader_version": LOADER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "logical_digest": digest,
        "row_counts": counts,
        "binary_reproducibility": "not_claimed; compare logical_digest and row_counts",
        "database": str(db_path),
    }
    if manifest_out:
        write_public_receipt_atomic(manifest_out, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="pg_catalog.csv")
    parser.add_argument("--db", default="books.sqlite")
    parser.add_argument("--rights", default="public_metadata")
    parser.add_argument("--source", default="project_gutenberg")
    parser.add_argument("--snapshot-id", default="unknown")
    parser.add_argument(
        "--source-uri",
        default="https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv",
    )
    parser.add_argument("--retrieved-at")
    parser.add_argument("--observed-at")
    parser.add_argument("--terms-revision", default="documented_unknown")
    parser.add_argument(
        "--rights-basis",
        default="Project Gutenberg catalog metadata; jurisdiction-specific text rights",
    )
    parser.add_argument("--acquisition-method", default="user_supplied_snapshot")
    parser.add_argument("--tier-sql")
    parser.add_argument("--manifest-out")
    arguments = parser.parse_args()
    print(json.dumps(build(
        csv_path=arguments.csv,
        db_path=arguments.db,
        rights=arguments.rights,
        source_id=arguments.source,
        snapshot_id=arguments.snapshot_id,
        source_uri=arguments.source_uri,
        retrieved_at=arguments.retrieved_at,
        observed_at=arguments.observed_at,
        terms_revision=arguments.terms_revision,
        rights_basis=arguments.rights_basis,
        acquisition_method=arguments.acquisition_method,
        tier_sql=arguments.tier_sql,
        manifest_out=arguments.manifest_out,
    ), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
