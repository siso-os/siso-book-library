#!/usr/bin/env python3
"""Export Book Library Works and contributor occurrences as pg-observation-0.1.

The NDJSON export never assigns a canonical People Graph ID. Contributor rows
are source-native Work/order occurrences; repeated labels remain separate and
carry only a comparison-only label hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Iterator

try:
    from scripts.common import (
        LOADER_VERSION,
        canonical_json,
        sha256_bytes,
        write_public_receipt_atomic,
    )
except ModuleNotFoundError:  # direct execution from scripts/
    from common import (  # type: ignore
        LOADER_VERSION,
        canonical_json,
        sha256_bytes,
        write_public_receipt_atomic,
    )

ENVELOPE_VERSION = "pg-observation-0.1"
ALLOWED_RIGHTS = {
    "public_metadata",
    "open_data",
    "restricted",
    "discovery_only",
    "pending",
}
ALLOWED_SUBJECT_KINDS = {
    "person", "organisation", "account", "work", "event", "venue", "place",
    "concept", "claim",
}
FORBIDDEN_ID_KEYS = {
    "canonical_id",
    "canonical_person_id",
    "canonical_people_graph_id",
    "people_graph_id",
}
NON_UNIQUE_IDENTIFIER_SCHEMES = {
    "name", "display_name", "real_name", "company", "employer", "location",
    "biography", "topic", "handle",
}


def _metadata(connection: sqlite3.Connection) -> dict[str, str]:
    row = connection.execute(
        """SELECT source_id, snapshot_id, source_sha256, retrieved_at, observed_at,
                  terms_revision, rights_state
           FROM source_manifest LIMIT 1"""
    ).fetchone()
    if row is None:
        raise ValueError("books database has no source_manifest row")
    return dict(zip(
        (
            "source_id", "snapshot_id", "source_sha256", "retrieved_at",
            "observed_at", "terms_revision", "rights_state",
        ),
        map(str, row),
    ))


def _source(meta: dict[str, str], native_id: str, payload: bytes) -> dict[str, object]:
    rights = meta["rights_state"]
    if rights not in ALLOWED_RIGHTS:
        # The interim contract has a closed rights vocabulary. Preserve any
        # source-specific wording in subject attributes, but do not invent a map.
        rights = "pending"
    return {
        "source_id": meta["source_id"],
        "snapshot_id": meta["snapshot_id"],
        "record_native_id": native_id,
        "observed_at": meta["observed_at"],
        "retrieved_at": meta["retrieved_at"],
        "terms_revision": meta["terms_revision"],
        "rights_state": rights,
        "payload_sha256": sha256_bytes(payload),
    }


def _find_forbidden_keys(value: object, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            folded = str(key).casefold()
            if folded in FORBIDDEN_ID_KEYS:
                errors.append(f"forbidden canonical key at {path}.{key}")
            if folded == "person_id" and isinstance(child, str) and child.startswith("bk:"):
                errors.append(f"forbidden name-derived person ID at {path}.{key}")
            errors.extend(_find_forbidden_keys(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_find_forbidden_keys(child, f"{path}[{index}]"))
    return errors


def validate_envelope(record: dict[str, object]) -> list[str]:
    """Validate the shared interim contract and Book Library safety invariants."""

    errors: list[str] = []
    if record.get("envelope_version") != ENVELOPE_VERSION:
        errors.append("wrong envelope_version")
    for required in (
        "source", "subject", "identifiers", "contributions", "relationships",
        "evidence", "raw_pointer",
    ):
        if required not in record:
            errors.append(f"missing {required}")
    errors.extend(_find_forbidden_keys(record))

    source = record.get("source")
    if not isinstance(source, dict):
        errors.append("source is not an object")
    else:
        required_source = {
            "source_id", "snapshot_id", "record_native_id", "observed_at",
            "retrieved_at", "terms_revision", "rights_state", "payload_sha256",
        }
        missing = sorted(required_source - set(source))
        if missing:
            errors.append(f"source missing fields: {missing}")
        if source.get("rights_state") not in ALLOWED_RIGHTS:
            errors.append("invalid rights_state")
        digest = source.get("payload_sha256")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            errors.append("invalid payload_sha256")

    subject = record.get("subject")
    if not isinstance(subject, dict):
        errors.append("subject is not an object")
    else:
        if subject.get("kind") not in ALLOWED_SUBJECT_KINDS:
            errors.append("invalid subject kind")
        for field in ("source_native_id", "label", "attributes"):
            if field not in subject:
                errors.append(f"subject missing {field}")

    identifiers = record.get("identifiers")
    if not isinstance(identifiers, list):
        errors.append("identifiers is not a list")
    else:
        for index, identifier in enumerate(identifiers):
            if not isinstance(identifier, dict):
                errors.append(f"identifier {index} is not an object")
                continue
            required_identifier = {
                "scheme", "value", "scope", "stability", "uniqueness", "evidence",
            }
            missing = sorted(required_identifier - set(identifier))
            if missing:
                errors.append(f"identifier {index} missing fields: {missing}")
            scheme = str(identifier.get("scheme", "")).casefold()
            if (
                scheme in NON_UNIQUE_IDENTIFIER_SCHEMES
                and identifier.get("scope") == "global"
                and identifier.get("uniqueness") == "unique"
            ):
                errors.append(
                    f"non-unique attribute promoted to a global unique identifier: {scheme}"
                )
            if identifier.get("scope") not in {"global", "source", "organisation"}:
                errors.append(f"identifier {index} has invalid scope")
            if identifier.get("stability") not in {"stable", "mutable", "unknown"}:
                errors.append(f"identifier {index} has invalid stability")
            if identifier.get("uniqueness") not in {"unique", "non_unique", "unknown"}:
                errors.append(f"identifier {index} has invalid uniqueness")

    for field in ("contributions", "relationships", "evidence"):
        if field in record and not isinstance(record[field], list):
            errors.append(f"{field} is not a list")
    if not isinstance(record.get("raw_pointer"), str):
        errors.append("raw_pointer is not a string")
    return errors


def _group_values(
    connection: sqlite3.Connection,
    table: str,
    value_columns: tuple[str, ...],
) -> dict[int, list[object]]:
    selected = ", ".join(("gid", *value_columns))
    order = ", ".join(("gid", *value_columns))
    grouped: dict[int, list[object]] = {}
    for row in connection.execute(f"SELECT {selected} FROM {table} ORDER BY {order}"):
        gid = int(row[0])
        value: object = row[1] if len(row) == 2 else dict(zip(value_columns, row[1:]))
        grouped.setdefault(gid, []).append(value)
    return grouped


def iter_records(books_db: str, contributors_db: str) -> Iterator[dict[str, object]]:
    books = sqlite3.connect(f"file:{Path(books_db).resolve()}?mode=ro", uri=True)
    contributors = sqlite3.connect(
        f"file:{Path(contributors_db).resolve()}?mode=ro", uri=True
    )
    try:
        meta = _metadata(books)
        subjects = _group_values(books, "book_subject", ("subject",))
        shelves = _group_values(books, "book_shelf", ("shelf",))
        classifications = _group_values(
            books, "book_class", ("locc", "section", "bookcase")
        )

        contribution_rows: dict[int, list[tuple[object, ...]]] = {}
        for row in contributors.execute(
            """SELECT c.gid, c.contribution_order, c.role, c.raw_label,
                      s.contributor_observation_id, s.source_label_key,
                      s.display_name, s.birth_year, s.death_year,
                      s.aliases_json, s.entity_kind_state, s.classification_method,
                      s.classification_evidence_json
               FROM contribution c
               JOIN source_contributor s USING(contributor_observation_id)
               ORDER BY c.gid, c.contribution_order"""
        ):
            contribution_rows.setdefault(int(row[0]), []).append(tuple(row[1:]))

        for (
            gid, title, authors, language, issued, media_type, text_url, rights, raw
        ) in books.execute(
            """SELECT gid, title, authors, language, issued, media_type, text_url,
                      rights, raw FROM book ORDER BY gid"""
        ):
            work_native_id = str(gid)
            work_contributions = []
            for contribution in contribution_rows.get(int(gid), []):
                (
                    order, role, raw_label, observation_id, label_key, *_rest
                ) = contribution
                work_contributions.append({
                    "contributor_observation_id": observation_id,
                    "source_label_key": label_key,
                    "source_label_key_semantics": "comparison_only_not_identity",
                    "role": role,
                    "order": order,
                    "label": raw_label,
                })
            work_record: dict[str, object] = {
                "envelope_version": ENVELOPE_VERSION,
                "source": _source(meta, work_native_id, str(raw).encode("utf-8")),
                "subject": {
                    "kind": "work",
                    "source_native_id": str(gid),
                    "label": title,
                    "attributes": {
                        "authors_raw": authors,
                        "language": language,
                        "issued": issued,
                        "media_type": media_type,
                        "text_url": text_url,
                        "rights": rights,
                        "subjects": subjects.get(int(gid), []),
                        "bookshelves": shelves.get(int(gid), []),
                        "locc": classifications.get(int(gid), []),
                    },
                },
                "identifiers": [{
                    "scheme": "gutenberg_ebook_id",
                    "value": str(gid),
                    "scope": "source",
                    "stability": "stable",
                    "uniqueness": "unique",
                    "evidence": "Project Gutenberg catalog Text# field",
                }],
                "contributions": work_contributions,
                "relationships": [],
                "evidence": [{
                    "kind": "source_row",
                    "locator": f"books.sqlite:book[gid={gid}]",
                    "source_field": "raw",
                    "inference": False,
                }],
                "raw_pointer": f"books.sqlite:book[gid={gid}].raw",
            }
            yield work_record

            for contribution in contribution_rows.get(int(gid), []):
                (
                    order, role, raw_label, observation_id, label_key, display_name,
                    birth, death, aliases_json, kind_state, classification_method,
                    classification_evidence_json,
                ) = contribution
                payload = canonical_json({
                    "gid": gid,
                    "order": order,
                    "role": role,
                    "raw_label": raw_label,
                }).encode("utf-8")
                contributor_record: dict[str, object] = {
                    "envelope_version": ENVELOPE_VERSION,
                    "source": _source(meta, str(observation_id), payload),
                    # The source does not reliably distinguish a human from an
                    # institution. `claim` is intentionally unresolved and honest.
                    "subject": {
                        "kind": "claim",
                        "source_native_id": observation_id,
                        "label": raw_label,
                        "attributes": {
                            "observation_type": "contributor_identity_candidate",
                            "display_name": display_name,
                            "aliases": json.loads(str(aliases_json)),
                            "birth_year": birth,
                            "death_year": death,
                            "entity_kind_state": kind_state,
                            "candidate_kinds": ["person", "organisation"],
                            "classification_method": classification_method,
                            "classification_evidence": json.loads(
                                str(classification_evidence_json)
                            ),
                            "source_label_key": label_key,
                            "source_label_key_semantics": "comparison_only_not_identity",
                        },
                    },
                    "identifiers": [],
                    "contributions": [{
                        "work_source_native_id": work_native_id,
                        "role": role,
                        "order": order,
                    }],
                    "relationships": [{
                        "predicate": "contributed_to",
                        "object_source_native_id": work_native_id,
                        "role": role,
                        "order": order,
                    }],
                    "evidence": [{
                        "kind": "literal_source_field",
                        "locator": f"books.sqlite:book[gid={gid}].authors#{order}",
                        "value": raw_label,
                        "inference": False,
                    }],
                    "raw_pointer": (
                        "contributors.sqlite:contribution"
                        f"[gid={gid},order={order}]"
                    ),
                }
                yield contributor_record
    finally:
        contributors.close()
        books.close()


def export(
    books_db: str,
    contributors_db: str,
    output_path: str,
    manifest_out: str | None = None,
) -> dict[str, object]:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    record_count = work_count = contributor_count = 0
    first_source: dict[str, object] | None = None
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for record in iter_records(books_db, contributors_db):
                errors = validate_envelope(record)
                if errors:
                    raise ValueError(f"invalid envelope: {errors}")
                line = canonical_json(record)
                handle.write(line + "\n")
                digest.update(line.encode("utf-8") + b"\n")
                record_count += 1
                if first_source is None:
                    first_source = dict(record["source"])  # type: ignore[arg-type]
                subject = record["subject"]
                if isinstance(subject, dict) and subject.get("kind") == "work":
                    work_count += 1
                else:
                    contributor_count += 1
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)

    logical = digest.hexdigest()
    summary: dict[str, object] = {
        "manifest_version": "book-library-observation-export-1",
        "envelope_version": ENVELOPE_VERSION,
        "records": record_count,
        "works": work_count,
        "contributor_observations": contributor_count,
        "row_counts": {
            "records": record_count,
            "works": work_count,
            "contributor_observations": contributor_count,
        },
        "sha256": logical,
        "logical_digest": logical,
        "output": str(output),
        "loader_version": LOADER_VERSION,
        "canonical_ids_assigned": False,
        "name_only_merges": False,
    }
    if first_source is not None:
        summary["source"] = {
            key: first_source.get(key)
            for key in (
                "source_id", "snapshot_id", "observed_at", "retrieved_at",
                "terms_revision", "rights_state",
            )
        }
    if manifest_out:
        write_public_receipt_atomic(manifest_out, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books", required=True)
    parser.add_argument("--contributors", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest-out")
    arguments = parser.parse_args()
    print(json.dumps(
        export(
            arguments.books,
            arguments.contributors,
            arguments.out,
            arguments.manifest_out,
        ),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
