#!/usr/bin/env python3
"""Export Book Library Work and contributor observations as pg-observation-0.1.

The export never emits a canonical People Graph identifier and never resolves
contributors because their labels match. Work records retain every source-listed
role and order. Contributor records identify attribution occurrences, not people.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable

from booklib import OBSERVATION_ENVELOPE_VERSION
from booklib.common import (
    ContractError,
    atomic_write_bytes,
    canonical_json,
    require_iso_utc,
    sha256_bytes,
    sha256_text,
    sqlite_readonly,
)

RIGHTS_STATES = {"public_metadata", "open_data", "restricted", "discovery_only", "pending"}
SUBJECT_KINDS = {"person", "organisation", "account", "work", "event", "venue", "place", "concept", "claim"}
STABILITIES = {"stable", "mutable", "unknown"}
UNIQUENESS = {"unique", "non_unique", "unknown"}
SCOPES = {"global", "source", "organisation"}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_CANONICAL_KEYS = {
    "canonical_id",
    "canonical_person_id",
    "canonical_entity_id",
    "resolved_person_id",
    "person_id",
    "merged_into",
}
ATTRIBUTE_ONLY_IDENTIFIER_SCHEMES = {
    "name",
    "real_name",
    "display_name",
    "company",
    "employer",
    "location",
    "biography",
    "topic",
}
HANDLE_SCHEMES = {"handle", "username", "login"}


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def validate_envelope(record: dict[str, Any]) -> None:
    if record.get("envelope_version") != OBSERVATION_ENVELOPE_VERSION:
        raise ContractError("unsupported observation envelope_version")
    forbidden = FORBIDDEN_CANONICAL_KEYS.intersection(_walk_keys(record))
    if forbidden:
        raise ContractError(
            "observation envelope contains forbidden canonical fields: "
            + ", ".join(sorted(forbidden))
        )
    source = record.get("source")
    subject = record.get("subject")
    if not isinstance(source, dict) or not isinstance(subject, dict):
        raise ContractError("source and subject must be objects")
    for field in (
        "source_id",
        "snapshot_id",
        "record_native_id",
        "observed_at",
        "retrieved_at",
        "terms_revision",
        "rights_state",
        "payload_sha256",
    ):
        if not source.get(field):
            raise ContractError(f"source.{field} is required")
    require_iso_utc(str(source["observed_at"]), "source.observed_at")
    require_iso_utc(str(source["retrieved_at"]), "source.retrieved_at")
    if source["rights_state"] not in RIGHTS_STATES:
        raise ContractError(f"invalid source.rights_state: {source['rights_state']}")
    if not SHA_RE.fullmatch(str(source["payload_sha256"])):
        raise ContractError("source.payload_sha256 must be a lowercase SHA-256")

    if subject.get("kind") not in SUBJECT_KINDS:
        raise ContractError(f"invalid subject.kind: {subject.get('kind')}")
    for field in ("source_native_id", "label", "attributes"):
        if field not in subject:
            raise ContractError(f"subject.{field} is required")
    if not isinstance(subject["attributes"], dict):
        raise ContractError("subject.attributes must be an object")

    for list_field in ("identifiers", "contributions", "relationships", "evidence"):
        if not isinstance(record.get(list_field), list):
            raise ContractError(f"{list_field} must be a list")
    if not isinstance(record.get("raw_pointer"), str) or not record["raw_pointer"]:
        raise ContractError("raw_pointer is required")

    for identifier in record["identifiers"]:
        if not isinstance(identifier, dict):
            raise ContractError("identifier entries must be objects")
        for field in ("scheme", "value", "scope", "stability", "uniqueness", "evidence"):
            if field not in identifier:
                raise ContractError(f"identifier.{field} is required")
        scheme = str(identifier["scheme"]).casefold()
        if scheme.startswith("canonical"):
            raise ContractError("canonical identifiers are prohibited in source observations")
        if scheme in ATTRIBUTE_ONLY_IDENTIFIER_SCHEMES:
            raise ContractError(f"attribute-like scheme {scheme!r} cannot be an identifier")
        if identifier["scope"] not in SCOPES:
            raise ContractError(f"invalid identifier scope: {identifier['scope']}")
        if identifier["stability"] not in STABILITIES:
            raise ContractError(f"invalid identifier stability: {identifier['stability']}")
        if identifier["uniqueness"] not in UNIQUENESS:
            raise ContractError(f"invalid identifier uniqueness: {identifier['uniqueness']}")
        if scheme in HANDLE_SCHEMES and (
            identifier["scope"] == "global"
            or identifier["stability"] == "stable"
            or identifier["uniqueness"] == "unique"
        ):
            raise ContractError(
                "handles/logins may only be mutable, source-scoped, non-unique or unknown identifiers"
            )
        if not str(identifier["evidence"]).strip():
            raise ContractError("identifier.evidence must be non-empty")


def _source_base(snapshot: sqlite3.Row, record_native_id: str, payload_sha256: str) -> dict[str, Any]:
    return {
        "source_id": snapshot["source_id"],
        "snapshot_id": snapshot["snapshot_id"],
        "record_native_id": record_native_id,
        "observed_at": snapshot["source_observed_at"],
        "retrieved_at": snapshot["retrieved_at"],
        "terms_revision": snapshot["terms_revision"],
        "rights_state": snapshot["rights_state"],
        "payload_sha256": payload_sha256,
    }


def _raw_pointer(snapshot: sqlite3.Row, gid: int) -> str:
    template = snapshot["raw_pointer_template"]
    try:
        return template.format(gid=gid)
    except (KeyError, ValueError) as exc:
        raise ContractError(f"invalid raw_pointer_template: {template}") from exc


def _book_record(
    books: sqlite3.Connection,
    contributors: sqlite3.Connection,
    snapshot: sqlite3.Row,
    book: sqlite3.Row,
) -> dict[str, Any]:
    gid = int(book["gid"])
    subjects = [
        row[0]
        for row in books.execute(
            "SELECT subject FROM book_subject WHERE gid=? ORDER BY subject", (gid,)
        )
    ]
    shelves = [
        row[0]
        for row in books.execute(
            "SELECT shelf FROM book_shelf WHERE gid=? ORDER BY shelf", (gid,)
        )
    ]
    classes = [
        {
            "locc": row["locc"],
            "section": row["section"],
            "subclass": row["bookcase"],
            "numeric_stem": row["numeric_stem"],
        }
        for row in books.execute(
            "SELECT locc,section,bookcase,numeric_stem FROM book_class "
            "WHERE gid=? ORDER BY locc",
            (gid,),
        )
    ]
    contribution_rows = contributors.execute(
        """SELECT observation_id,contribution_order,role,role_observed,
                  display_label,raw_label,entity_kind_state,raw_sha256
           FROM contributor_observation WHERE gid=? ORDER BY contribution_order""",
        (gid,),
    ).fetchall()
    contributions = [
        {
            "contributor_source_native_id": row["observation_id"],
            "label": row["display_label"],
            "raw_label": row["raw_label"],
            "role": row["role"],
            "role_observed": row["role_observed"],
            "order": row["contribution_order"],
            "entity_kind_state": row["entity_kind_state"],
            "evidence_sha256": row["raw_sha256"],
        }
        for row in contribution_rows
    ]
    relationships = [
        {
            "type": "classified_as",
            "object_kind": "concept",
            "object_source_native_id": f"gutenberg:subject:{sha256_text(subject)[:24]}",
            "label": subject,
            "vocabulary": "project_gutenberg_subject",
        }
        for subject in subjects
    ]
    relationships.extend(
        {
            "type": "shelved_as",
            "object_kind": "concept",
            "object_source_native_id": f"gutenberg:shelf:{sha256_text(shelf)[:24]}",
            "label": shelf,
            "vocabulary": "project_gutenberg_bookshelf",
        }
        for shelf in shelves
    )
    relationships.extend(
        {
            "type": "classified_as",
            "object_kind": "concept",
            "object_source_native_id": f"lcc:{item['locc']}",
            "label": item["locc"],
            "vocabulary": "library_of_congress_classification",
        }
        for item in classes
    )
    pointer = _raw_pointer(snapshot, gid)
    return {
        "envelope_version": OBSERVATION_ENVELOPE_VERSION,
        "source": _source_base(snapshot, f"ebook:{gid}", book["raw_sha256"]),
        "subject": {
            "kind": "work",
            "source_native_id": str(gid),
            "label": book["title"],
            "attributes": {
                "work_type": "ebook_catalog_record",
                "language": book["language"],
                "issued": book["issued"],
                "issued_semantics": "project_gutenberg_release_date_not_print_date",
                "media_type": book["media_type"],
                "text_url": book["text_url"],
                "authors_raw": book["authors"],
                "payload_rights_observed": book["rights"],
                "payload_rights_state": book["payload_rights_state"],
                "subjects": subjects,
                "shelves": shelves,
                "lcc": classes,
            },
        },
        "identifiers": [
            {
                "scheme": "gutenberg_ebook_id",
                "value": str(gid),
                "scope": "source",
                "stability": "stable",
                "uniqueness": "unique",
                "evidence": "literal Project Gutenberg catalog Text# field",
            }
        ],
        "contributions": contributions,
        "relationships": relationships,
        "evidence": [
            {
                "evidence_type": "source_record",
                "locator": pointer,
                "payload_sha256": book["raw_sha256"],
                "literal_fields": [
                    "Text#",
                    "Title",
                    "Authors",
                    "Subjects",
                    "LoCC",
                    "Bookshelves",
                    "Rights or Copyright Status",
                ],
            }
        ],
        "raw_pointer": pointer,
    }


def _contributor_record(snapshot: sqlite3.Row, row: sqlite3.Row) -> dict[str, Any]:
    gid = int(row["gid"])
    pointer = _raw_pointer(snapshot, gid)
    evidence = {
        "raw_label": row["raw_label"],
        "role_observed": row["role_observed"],
        "kind_evidence": json.loads(row["kind_evidence_json"]),
        "pseudonym_markers": json.loads(row["pseudonym_markers_json"]),
        "work_source_native_id": str(gid),
        "contribution_order": row["contribution_order"],
    }
    evidence_sha = sha256_text(canonical_json(evidence))
    if evidence_sha != row["raw_sha256"]:
        raise ContractError(f"contributor evidence digest mismatch: {row['observation_id']}")
    return {
        "envelope_version": OBSERVATION_ENVELOPE_VERSION,
        "source": _source_base(snapshot, row["observation_id"], evidence_sha),
        "subject": {
            "kind": "claim",
            "source_native_id": row["observation_id"],
            "label": row["display_label"],
            "attributes": {
                "claim_type": "contribution_attribution",
                "identity_state": "unresolved",
                "entity_kind_state": row["entity_kind_state"],
                "kind_evidence": json.loads(row["kind_evidence_json"]),
                "aliases": json.loads(row["aliases_json"]),
                "pseudonym_markers": json.loads(row["pseudonym_markers_json"]),
                "birth_year_observed": row["birth_year"],
                "death_year_observed": row["death_year"],
                "raw_label": row["raw_label"],
            },
        },
        "identifiers": [
            {
                "scheme": "gutenberg_work_contributor_ordinal",
                "value": row["observation_id"],
                "scope": "source",
                "stability": "mutable",
                "uniqueness": "unique",
                "evidence": (
                    "derived from literal Text# plus source-listed contributor order; "
                    "identifies an attribution occurrence, not a person"
                ),
            }
        ],
        "contributions": [
            {
                "work_source_native_id": str(gid),
                "role": row["role"],
                "role_observed": row["role_observed"],
                "order": row["contribution_order"],
            }
        ],
        "relationships": [
            {
                "type": "contributed_to",
                "object_kind": "work",
                "object_source_native_id": str(gid),
                "role": row["role"],
                "order": row["contribution_order"],
            }
        ],
        "evidence": [
            {
                "evidence_type": "literal_attribution",
                "locator": pointer,
                "literal_value": row["raw_label"],
                "payload_sha256": evidence_sha,
            }
        ],
        "raw_pointer": pointer,
    }


def export_records(books_db: str | Path, contributors_db: str | Path) -> list[dict[str, Any]]:
    with sqlite_readonly(books_db) as books, sqlite_readonly(contributors_db) as contributors:
        snapshot = books.execute("SELECT * FROM source_snapshot").fetchone()
        contributor_snapshot = contributors.execute("SELECT * FROM source_snapshot").fetchone()
        if snapshot is None or contributor_snapshot is None:
            raise ContractError("source_snapshot missing from input database")
        if (snapshot["source_id"], snapshot["snapshot_id"]) != (
            contributor_snapshot["source_id"],
            contributor_snapshot["snapshot_id"],
        ):
            raise ContractError("books and contributors databases describe different snapshots")
        records: list[dict[str, Any]] = []
        for book in books.execute("SELECT * FROM book ORDER BY gid"):
            records.append(_book_record(books, contributors, snapshot, book))
        for row in contributors.execute(
            "SELECT * FROM contributor_observation ORDER BY gid, contribution_order"
        ):
            records.append(_contributor_record(snapshot, row))
        records.sort(
            key=lambda item: (
                item["source"]["record_native_id"],
                item["subject"]["kind"],
            )
        )
        for record in records:
            validate_envelope(record)
        return records


def write_ndjson(records: list[dict[str, Any]], output_path: str | Path) -> dict[str, Any]:
    payload = "".join(canonical_json(record) + "\n" for record in records).encode("utf-8")
    atomic_write_bytes(output_path, payload)
    counts: dict[str, int] = {}
    for record in records:
        kind = record["subject"]["kind"]
        counts[kind] = counts.get(kind, 0) + 1
    return {
        "records": len(records),
        "subject_kind_counts": dict(sorted(counts.items())),
        "ndjson_sha256": sha256_bytes(payload),
        "output": str(output_path),
    }


def validate_ndjson(path: str | Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    kinds: dict[str, int] = {}
    with open(path, "rb") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            digest.update(raw_line)
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ContractError(f"line {line_number}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ContractError(f"line {line_number}: record must be an object")
            try:
                validate_envelope(record)
            except ContractError as exc:
                raise ContractError(f"line {line_number}: {exc}") from exc
            kind = record["subject"]["kind"]
            kinds[kind] = kinds.get(kind, 0) + 1
            count += 1
    return {
        "records": count,
        "subject_kind_counts": dict(sorted(kinds.items())),
        "ndjson_sha256": digest.hexdigest(),
        "path": str(path),
        "valid": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books")
    parser.add_argument("--contributors")
    parser.add_argument("--out")
    parser.add_argument("--validate")
    args = parser.parse_args()
    try:
        if args.validate:
            result = validate_ndjson(args.validate)
        else:
            if not (args.books and args.contributors and args.out):
                parser.error("--books, --contributors, and --out are required for export")
            result = write_ndjson(export_records(args.books, args.contributors), args.out)
    except (ContractError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
