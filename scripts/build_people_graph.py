#!/usr/bin/env python3
"""Build source-native contributor observations from the Book index.

Every catalog attribution remains a separate occurrence keyed by Gutenberg Work
and source order. Labels, aliases, roles, pseudonym markers, life dates, Unicode,
and unresolved institution/person status are preserved as evidence. No normalized
name is promoted to a canonical person identifier and no two occurrences merge.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from booklib import CONTRIBUTOR_GRAPH_SCHEMA_VERSION, LOADER_VERSION
from booklib.common import (
    ContractError,
    atomic_database_path,
    canonical_json,
    nfc,
    sha256_text,
    sqlite_logical_snapshot,
    sqlite_readonly,
)

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
  payload_sha256       TEXT NOT NULL CHECK(length(payload_sha256) = 64),
  raw_pointer_template TEXT NOT NULL,
  loader_version       TEXT NOT NULL,
  schema_version       TEXT NOT NULL,
  PRIMARY KEY (source_id, snapshot_id)
);

CREATE TABLE contributor_observation (
  observation_id       TEXT PRIMARY KEY,
  gid                  INTEGER NOT NULL,
  contribution_order   INTEGER NOT NULL CHECK(contribution_order > 0),
  role                 TEXT NOT NULL,
  role_observed        TEXT,
  display_label        TEXT NOT NULL,
  raw_label            TEXT NOT NULL,
  aliases_json         TEXT NOT NULL,
  pseudonym_markers_json TEXT NOT NULL,
  birth_year           INTEGER,
  death_year           INTEGER,
  entity_kind_state    TEXT NOT NULL CHECK(entity_kind_state IN
                           ('unknown','person_candidate','organisation_candidate')),
  kind_evidence_json   TEXT NOT NULL,
  source_id            TEXT NOT NULL,
  snapshot_id          TEXT NOT NULL,
  observed_at          TEXT NOT NULL,
  raw_sha256           TEXT NOT NULL CHECK(length(raw_sha256) = 64),
  UNIQUE (gid, contribution_order),
  FOREIGN KEY (source_id, snapshot_id)
    REFERENCES source_snapshot(source_id, snapshot_id)
);

CREATE TABLE contribution (
  observation_id     TEXT NOT NULL,
  gid                INTEGER NOT NULL,
  role               TEXT NOT NULL,
  contribution_order INTEGER NOT NULL,
  PRIMARY KEY (observation_id, gid, role, contribution_order),
  FOREIGN KEY (observation_id)
    REFERENCES contributor_observation(observation_id) ON DELETE CASCADE
);

CREATE INDEX ix_contributor_gid   ON contributor_observation(gid);
CREATE INDEX ix_contributor_label ON contributor_observation(display_label);
CREATE INDEX ix_contribution_gid  ON contribution(gid);

-- Compatibility views preserve old read names while making the non-canonical
-- semantics explicit: one row is one source occurrence, not one resolved person.
CREATE VIEW person AS
SELECT
  observation_id AS person_key,
  display_label AS display_name,
  display_label AS sort_name,
  birth_year,
  death_year,
  NULL AS is_corporate,
  aliases_json AS raw_variants,
  1 AS work_count
FROM contributor_observation;

CREATE VIEW person_work AS
SELECT observation_id AS person_key, gid, role
FROM contribution;
"""

ROLE = re.compile(r"\[([^\]]+)\]\s*$")
CE_RANGE = re.compile(r",\s*(?:ca\.\s*)?(\d{3,4})\??\s*-\s*(\d{3,4})?\??\s*$", re.I)
OPEN_YEAR = re.compile(r",\s*(b\.|d\.)\s*(\d{3,4})\??\s*$", re.I)
BCE_RANGE = re.compile(
    r",\s*(?:ca\.\s*)?(\d{1,4})\??\s*(?:BCE|B\.C\.?E?\.?)\s*-\s*"
    r"(\d{1,4})?\??\s*(?:BCE|B\.C\.?E?\.?)?\s*$",
    re.I,
)
PSEUDONYM_MARKER = re.compile(
    r"\(([^()]*(?:pseud\.?|pseudonym|pen\s+name)[^()]*)\)", re.I
)


@dataclass(frozen=True)
class ParsedContributor:
    display_label: str
    raw_label: str
    aliases: tuple[str, ...]
    pseudonym_markers: tuple[str, ...]
    role: str
    role_observed: str | None
    birth_year: int | None
    death_year: int | None
    entity_kind_state: str
    kind_evidence: tuple[dict[str, str], ...]


def split_contributors(authors: str | None) -> list[str]:
    return [nfc(part.strip()) for part in (authors or "").split(";") if part.strip()]


def normalize_role(value: str | None) -> str:
    if not value:
        return "author"
    role = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return role or "contributor"


def _unique(values: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = nfc(value.strip())
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return tuple(result)


def parse_contributor(raw: str) -> ParsedContributor:
    raw_label = nfc(raw.strip())
    if not raw_label:
        raise ContractError("empty contributor label")

    working = raw_label
    role_observed: str | None = None
    role_match = ROLE.search(working)
    if role_match:
        role_observed = role_match.group(1).strip()
        working = working[: role_match.start()].strip()
    role = normalize_role(role_observed)

    birth = death = None
    evidence: list[dict[str, str]] = []
    bce = BCE_RANGE.search(working)
    if bce:
        birth = -int(bce.group(1))
        death = -int(bce.group(2)) if bce.group(2) else None
        evidence.append(
            {"method": "literal_life_dates", "value": bce.group(0).strip(" ,")}
        )
        working = working[: bce.start()].strip()
    else:
        ce = CE_RANGE.search(working)
        if ce:
            birth = int(ce.group(1))
            death = int(ce.group(2)) if ce.group(2) else None
            evidence.append(
                {"method": "literal_life_dates", "value": ce.group(0).strip(" ,")}
            )
            working = working[: ce.start()].strip()
        else:
            open_match = OPEN_YEAR.search(working)
            if open_match:
                year = int(open_match.group(2))
                if open_match.group(1).casefold().startswith("b"):
                    birth = year
                else:
                    death = year
                evidence.append(
                    {
                        "method": "literal_life_date",
                        "value": open_match.group(0).strip(" ,"),
                    }
                )
                working = working[: open_match.start()].strip()

    display = working.strip().strip(",").strip() or raw_label
    parenthetical_aliases = re.findall(r"\(([^()]*)\)", display)
    pseudonym_markers = [match.group(1).strip() for match in PSEUDONYM_MARKER.finditer(display)]
    if pseudonym_markers:
        evidence.extend(
            {"method": "literal_pseudonym_marker", "value": marker}
            for marker in pseudonym_markers
        )

    # Life dates make "person" a source-supported candidate, not accepted truth.
    # Absence of dates or presence of organisation-like words is never used as a
    # hidden classifier. Explicit future source kind fields can promote state.
    if birth is not None or death is not None:
        kind_state = "person_candidate"
    else:
        kind_state = "unknown"
        evidence.append(
            {
                "method": "unresolved",
                "value": "catalog supplies no explicit person/organisation kind",
            }
        )

    return ParsedContributor(
        display_label=display,
        raw_label=raw_label,
        aliases=_unique([raw_label, display, *parenthetical_aliases]),
        pseudonym_markers=_unique(pseudonym_markers),
        role=role,
        role_observed=role_observed,
        birth_year=birth,
        death_year=death,
        entity_kind_state=kind_state,
        kind_evidence=tuple(evidence),
    )


def _copy_snapshot(source: sqlite3.Connection, destination: sqlite3.Connection) -> sqlite3.Row:
    row = source.execute("SELECT * FROM source_snapshot").fetchone()
    if row is None:
        raise ContractError("books database has no source_snapshot")
    destination.execute(
        "INSERT INTO source_snapshot VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            row["source_id"],
            row["snapshot_id"],
            row["source_uri"],
            row["source_observed_at"],
            row["retrieved_at"],
            row["terms_revision"],
            row["rights_state"],
            row["rights_basis"],
            row["payload_sha256"],
            row["raw_pointer_template"],
            LOADER_VERSION,
            CONTRIBUTOR_GRAPH_SCHEMA_VERSION,
        ),
    )
    return row


def _build_database(books_db: Path, output_db: Path) -> dict[str, object]:
    with sqlite_readonly(books_db) as books, contextlib.closing(sqlite3.connect(output_db)) as destination:
        destination.row_factory = sqlite3.Row
        destination.executescript(SCHEMA)
        snapshot = _copy_snapshot(books, destination)
        roles: set[str] = set()
        counts: dict[str, object] = {
            "contributor_observations": 0,
            "contribution_edges": 0,
            "person_candidates": 0,
            "unknown_entity_kind": 0,
            "pseudonym_marker_observations": 0,
        }
        rows = books.execute(
            "SELECT gid, authors, raw_sha256 FROM book "
            "WHERE trim(authors) != '' ORDER BY gid"
        )
        for row in rows:
            gid = int(row["gid"])
            for order, raw_contributor in enumerate(
                split_contributors(row["authors"]), start=1
            ):
                parsed = parse_contributor(raw_contributor)
                observation_id = f"gutenberg:ebook:{gid}:contributor:{order}"
                evidence_payload = {
                    "raw_label": parsed.raw_label,
                    "role_observed": parsed.role_observed,
                    "kind_evidence": list(parsed.kind_evidence),
                    "pseudonym_markers": list(parsed.pseudonym_markers),
                    "work_source_native_id": str(gid),
                    "contribution_order": order,
                }
                evidence_sha = sha256_text(canonical_json(evidence_payload))
                destination.execute(
                    """INSERT INTO contributor_observation VALUES
                       (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        observation_id,
                        gid,
                        order,
                        parsed.role,
                        parsed.role_observed,
                        parsed.display_label,
                        parsed.raw_label,
                        canonical_json(list(parsed.aliases)),
                        canonical_json(list(parsed.pseudonym_markers)),
                        parsed.birth_year,
                        parsed.death_year,
                        parsed.entity_kind_state,
                        canonical_json(list(parsed.kind_evidence)),
                        snapshot["source_id"],
                        snapshot["snapshot_id"],
                        snapshot["source_observed_at"],
                        evidence_sha,
                    ),
                )
                destination.execute(
                    "INSERT INTO contribution VALUES (?,?,?,?)",
                    (observation_id, gid, parsed.role, order),
                )
                roles.add(parsed.role)
                counts["contributor_observations"] = int(counts["contributor_observations"]) + 1
                counts["contribution_edges"] = int(counts["contribution_edges"]) + 1
                if parsed.entity_kind_state == "person_candidate":
                    counts["person_candidates"] = int(counts["person_candidates"]) + 1
                else:
                    counts["unknown_entity_kind"] = int(counts["unknown_entity_kind"]) + 1
                counts["pseudonym_marker_observations"] = int(
                    counts["pseudonym_marker_observations"]
                ) + len(parsed.pseudonym_markers)
        destination.commit()
        destination.execute("VACUUM")
    counts["roles"] = sorted(roles)
    return counts


def build(books_db: str | Path, db_path: str | Path) -> dict[str, object]:
    books_path = Path(books_db)
    destination = Path(db_path)
    if not books_path.is_file():
        raise ContractError(f"books database does not exist: {books_path}")
    with atomic_database_path(destination) as temporary:
        counts = _build_database(books_path, temporary)
    return {
        **counts,
        "db": str(destination),
        "schema_version": CONTRIBUTOR_GRAPH_SCHEMA_VERSION,
        "loader_version": LOADER_VERSION,
        **sqlite_logical_snapshot(destination),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books", default="books.sqlite")
    parser.add_argument("--db", default="people.sqlite")
    args = parser.parse_args()
    try:
        summary = build(args.books, args.db)
    except (ContractError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
