from __future__ import annotations

import contextlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from support import CATALOG_V1, CATALOG_V2, build_pair
from booklib.common import load_source_manifest
from build_books_module import build as build_books, default_tier_sql, parse_locc
from build_people_graph import build as build_contributors


class BookIndexIntegrityTests(unittest.TestCase):
    def test_lcc_letter_digit_parsing_agrees_with_lcc_structure(self):
        self.assertEqual(
            parse_locc("D501"),
            {"locc": "D501", "section": "D", "subclass": "D", "numeric_stem": "501"},
        )
        self.assertEqual(
            parse_locc("PR 6019"),
            {"locc": "PR6019", "section": "P", "subclass": "PR", "numeric_stem": "6019"},
        )
        self.assertEqual(
            parse_locc("QA76.73"),
            {"locc": "QA76.73", "section": "Q", "subclass": "QA", "numeric_stem": "76.73"},
        )
        self.assertIsNone(parse_locc("5D"))

    def test_two_clean_builds_have_equal_logical_digests(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            _, _, first_books, first_people = build_pair(Path(first))
            _, _, second_books, second_people = build_pair(Path(second))
            self.assertEqual(first_books["logical_sha256"], second_books["logical_sha256"])
            self.assertEqual(first_books["table_counts"], second_books["table_counts"])
            self.assertEqual(first_people["logical_sha256"], second_people["logical_sha256"])
            self.assertEqual(first_people["table_counts"], second_people["table_counts"])
            self.assertEqual(
                first_books["source_payload_sha256"],
                "fff72a45518bb4877626825761d38f57ee8e8619b3e222171432065d60b11fe7",
            )

    def test_catalog_and_contributor_source_replacement_removes_stale_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            books = root / "books.sqlite"
            contributors = root / "contributors.sqlite"
            build_books(load_source_manifest(CATALOG_V1), books, default_tier_sql())
            build_contributors(books, contributors)
            with contextlib.closing(sqlite3.connect(contributors)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM contributor_observation").fetchone()[0],
                    6,
                )

            build_books(load_source_manifest(CATALOG_V2), books, default_tier_sql())
            build_contributors(books, contributors)
            with contextlib.closing(sqlite3.connect(books)) as connection:
                self.assertEqual(
                    [row[0] for row in connection.execute("SELECT gid FROM book ORDER BY gid")],
                    [1001, 1003, 1004],
                )
                self.assertEqual(
                    [row[0] for row in connection.execute(
                        "SELECT subject FROM book_subject WHERE gid=1001 ORDER BY subject"
                    )],
                    ["Science"],
                )
                self.assertEqual(
                    [row[0] for row in connection.execute(
                        "SELECT locc FROM book_class WHERE gid=1001 ORDER BY locc"
                    )],
                    ["Q1"],
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM book_field WHERE field='Legacy Field'"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute("SELECT snapshot_id FROM source_snapshot").fetchone()[0],
                    "fixture-2026-08-06-v2",
                )
            with contextlib.closing(sqlite3.connect(contributors)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM contributor_observation").fetchone()[0],
                    3,
                )
                self.assertEqual(
                    set(row[0] for row in connection.execute("SELECT role FROM contribution")),
                    {"editor", "translator"},
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM contributor_observation WHERE gid=1002"
                    ).fetchone()[0],
                    0,
                )

    def test_roles_aliases_unicode_pseudonym_and_unknown_kind_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            books, contributors, _, people_result = build_pair(Path(temporary))
            self.assertEqual(
                set(people_result["roles"]), {"author", "translator", "editor", "compiler"}
            )
            with contextlib.closing(sqlite3.connect(contributors)) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    "SELECT * FROM contributor_observation WHERE gid=1001 ORDER BY contribution_order"
                ).fetchall()
                self.assertEqual([row["role"] for row in rows], ["author", "translator"])
                self.assertIn("García Márquez", rows[0]["display_label"])
                self.assertIn("A. G. Márquez", json.loads(rows[1]["aliases_json"]))

                pseudonym = connection.execute(
                    "SELECT * FROM contributor_observation WHERE gid=1002 AND contribution_order=2"
                ).fetchone()
                self.assertIn("pseud. River", json.loads(pseudonym["aliases_json"]))
                self.assertEqual(
                    json.loads(pseudonym["pseudonym_markers_json"]), ["pseud. River"]
                )

                institution = connection.execute(
                    "SELECT entity_kind_state FROM contributor_observation "
                    "WHERE gid=1002 AND contribution_order=1"
                ).fetchone()[0]
                self.assertEqual(institution, "unknown")
                non_text = connection.execute(
                    "SELECT role,entity_kind_state FROM contributor_observation WHERE gid=1005"
                ).fetchone()
                self.assertEqual(tuple(non_text), ("compiler", "unknown"))

    def test_extraction_queue_is_one_row_per_work_with_auditable_overlap(self):
        with tempfile.TemporaryDirectory() as temporary:
            books, _, _, _ = build_pair(Path(temporary))
            with contextlib.closing(sqlite3.connect(books)) as connection:
                connection.row_factory = sqlite3.Row
                count, distinct_count = connection.execute(
                    "SELECT COUNT(*),COUNT(DISTINCT gid) FROM v_extraction_queue"
                ).fetchone()
                self.assertEqual(count, distinct_count)
                self.assertEqual(count, 3)

                first = connection.execute(
                    "SELECT * FROM v_extraction_queue WHERE gid=1001"
                ).fetchone()
                self.assertEqual(first["tier"], "tier1")
                self.assertEqual(
                    first["reason_list"], "core_sections|biography|essays_letters_speeches"
                )
                self.assertEqual(first["reason_count"], 3)

                overlap = connection.execute(
                    "SELECT * FROM v_extraction_queue WHERE gid=1002"
                ).fetchone()
                self.assertEqual(overlap["tier"], "tier1")
                self.assertEqual(
                    overlap["reason_list"],
                    "criticism_PN|essays_letters_speeches|journalism_periodicals",
                )
                self.assertTrue(overlap["all_reason_list"].endswith("hold_revisit"))


if __name__ == "__main__":
    unittest.main()
