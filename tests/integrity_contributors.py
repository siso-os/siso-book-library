from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.build_books_module import build as build_books
from scripts.build_people_graph import build as build_contributors
from scripts.export_people_graph_observations import (
    export as export_observations, validate_envelope,
)
from tests.integrity_helpers import row, write_catalog

class ContributorAndEnvelopeTests(unittest.TestCase):
    def test_roles_unicode_aliases_and_source_replacement_without_name_merge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.csv"
            write_catalog(catalog, [
                row(
                    1,
                    "First",
                    "Doe, Jane [Author]; DOE, JANE [Editor]; 平塚, らいてう",
                ),
                row(2, "Second", "Twain, Mark (Samuel Clemens), 1835-1910 [Translator]"),
            ])
            books = root / "books.sqlite"
            contributors = root / "contributors.sqlite"
            build_books(str(catalog), str(books), snapshot_id="contributors-v1")
            build_contributors(str(books), str(contributors))
            connection = sqlite3.connect(contributors)
            # Different literal source labels are review candidates, not a merge.
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM source_contributor").fetchone()[0],
                4,
            )
            roles = [value for (value,) in connection.execute(
                "SELECT role FROM contribution ORDER BY gid, contribution_order"
            )]
            self.assertEqual(roles, ["author", "editor", "author", "translator"])
            unicode_label = connection.execute(
                "SELECT source_label FROM source_contributor WHERE source_label LIKE '平塚%'"
            ).fetchone()[0]
            self.assertEqual(unicode_label, "平塚, らいてう")
            alias_json = connection.execute(
                "SELECT aliases_json FROM source_contributor WHERE source_label LIKE 'Twain%'"
            ).fetchone()[0]
            self.assertEqual(json.loads(alias_json), ["Samuel Clemens"])
            self.assertTrue(all(value is None for (value,) in connection.execute(
                "SELECT is_corporate FROM person"
            )))
            connection.close()

            write_catalog(catalog, [row(1, "First", "Doe, Jane [Author]")])
            build_books(str(catalog), str(books), snapshot_id="contributors-v2")
            build_contributors(str(books), str(contributors))
            connection = sqlite3.connect(contributors)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM contribution").fetchone()[0], 1)
            self.assertEqual(
                connection.execute("SELECT DISTINCT gid FROM contribution").fetchall(),
                [(1,)],
            )
            connection.close()

    def test_pg_observation_export_has_no_canonical_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.csv"
            write_catalog(catalog, [
                row(
                    7,
                    "Unicode and institutions",
                    "United Nations [Editor]; 平塚, らいてう; Twain, Mark (Samuel Clemens) [Translator]",
                    "Biography",
                    "D501",
                ),
            ])
            books = root / "books.sqlite"
            contributors = root / "contributors.sqlite"
            output = root / "observations.ndjson"
            build_books(
                str(catalog), str(books), snapshot_id="export-v1",
                retrieved_at="2026-08-06T00:00:00Z",
                terms_revision="fixture-terms-v1",
            )
            build_contributors(str(books), str(contributors))
            summary = export_observations(str(books), str(contributors), str(output))
            self.assertFalse(summary["canonical_ids_assigned"])
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 4)
            self.assertTrue(all(not validate_envelope(record) for record in records))
            text = output.read_text(encoding="utf-8")
            self.assertNotIn("canonical_person_id", text)
            self.assertNotIn('"person_id":"bk:', text)
            work_record = next(r for r in records if r["subject"]["kind"] == "work")
            self.assertEqual(work_record["subject"]["attributes"]["subjects"], ["Biography"])
            self.assertEqual(
                work_record["subject"]["attributes"]["locc"],
                [{"bookcase": "D5", "locc": "D501", "section": "D"}],
            )
            contributor_records = [r for r in records if r["subject"]["kind"] == "claim"]
            self.assertTrue(all(r["identifiers"] == [] for r in contributor_records))
            self.assertEqual(
                {r["relationships"][0]["role"] for r in contributor_records},
                {"author", "editor", "translator"},
            )
            self.assertIn("平塚, らいてう", {r["subject"]["label"] for r in contributor_records})
            self.assertIn(
                "United Nations [Editor]",
                {r["subject"]["label"] for r in contributor_records},
            )


    def test_repeated_exact_labels_are_separate_occurrences(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.csv"
            write_catalog(catalog, [
                row(1, "First", "Doe, Jane [Author]"),
                row(2, "Second", "Doe, Jane [Author]"),
            ])
            books = root / "books.sqlite"
            contributors = root / "contributors.sqlite"
            build_books(str(catalog), str(books), snapshot_id="same-name-fixture")
            build_contributors(str(books), str(contributors))
            connection = sqlite3.connect(contributors)
            observed = connection.execute(
                """SELECT COUNT(*), COUNT(DISTINCT contributor_observation_id),
                          COUNT(DISTINCT source_label_key)
                   FROM source_contributor
                   WHERE source_label='Doe, Jane [Author]'"""
            ).fetchone()
            self.assertEqual(observed, (2, 2, 1))
            self.assertEqual(
                connection.execute(
                    "SELECT occurrences FROM source_label_frequency"
                ).fetchone()[0],
                2,
            )
            connection.close()

    def test_envelope_validator_rejects_canonical_and_name_identifier(self) -> None:
        record = {
            "envelope_version": "pg-observation-0.1",
            "source": {
                "source_id": "fixture",
                "snapshot_id": "v1",
                "record_native_id": "1",
                "observed_at": "2026-08-06T00:00:00Z",
                "retrieved_at": "2026-08-06T00:00:00Z",
                "terms_revision": "fixture",
                "rights_state": "public_metadata",
                "payload_sha256": "a" * 64,
            },
            "subject": {
                "kind": "claim",
                "source_native_id": "1",
                "label": "Doe, Jane",
                "attributes": {"canonical_person_id": "person:1"},
            },
            "identifiers": [{
                "scheme": "name",
                "value": "Doe, Jane",
                "scope": "global",
                "stability": "mutable",
                "uniqueness": "unique",
                "evidence": "literal",
            }],
            "contributions": [],
            "relationships": [],
            "evidence": [],
            "raw_pointer": "fixture",
        }
        errors = validate_envelope(record)
        self.assertTrue(any("forbidden canonical key" in error for error in errors))
        self.assertTrue(any("global unique identifier" in error for error in errors))


