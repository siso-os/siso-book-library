from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.build_books_module import build as build_books, parse_locc
from tests.integrity_helpers import row, write_catalog

class BookIndexIntegrityTests(unittest.TestCase):
    def test_locc_letter_plus_digit_and_letter_subclasses(self) -> None:
        self.assertEqual(parse_locc("D501"), ("D", "D5"))
        self.assertEqual(parse_locc("PR838"), ("P", "PR"))
        self.assertEqual(parse_locc(" q 11 "), ("Q", "Q1"))
        self.assertEqual(parse_locc("A"), ("A", "A"))
        self.assertIsNone(parse_locc("X999"))

    def test_source_replacement_and_timestamp_independent_logical_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.csv"
            second = root / "second.csv"
            write_catalog(first, [
                row(1, "Kept", "Doe, Jane", "Old Subject", "PR", "Old Shelf"),
                row(2, "Removed", "Roe, Richard", "Stale Subject", "D501", "Stale Shelf"),
            ])
            write_catalog(second, [
                row(1, "Kept Updated", "Doe, Jane", "New Subject", "Q11", "New Shelf"),
            ])
            database = root / "books.sqlite"
            build_books(
                str(first), str(database), snapshot_id="fixture-v1",
                retrieved_at="2026-08-06T00:00:00Z",
                observed_at="2026-08-06T00:00:00Z",
            )
            build_books(
                str(second), str(database), snapshot_id="fixture-v2",
                retrieved_at="2026-08-07T00:00:00Z",
                observed_at="2026-08-07T00:00:00Z",
            )
            connection = sqlite3.connect(database)
            self.assertEqual(connection.execute("SELECT gid FROM book").fetchall(), [(1,)])
            self.assertEqual(
                connection.execute("SELECT subject FROM book_subject").fetchall(),
                [("New Subject",)],
            )
            self.assertEqual(
                connection.execute("SELECT shelf FROM book_shelf").fetchall(),
                [("New Shelf",)],
            )
            self.assertEqual(
                connection.execute("SELECT locc, bookcase FROM book_class").fetchall(),
                [("Q11", "Q1")],
            )
            connection.close()

            build_a = build_books(
                str(second), str(root / "a.sqlite"), snapshot_id="fixture-v2",
                retrieved_at="2026-08-07T00:00:00Z",
                observed_at="2026-08-07T00:00:00Z",
            )
            build_b = build_books(
                str(second), str(root / "b.sqlite"), snapshot_id="fixture-v2",
                retrieved_at="2026-09-01T12:34:56Z",
                observed_at="2026-09-01T12:34:56Z",
            )
            self.assertEqual(build_a["logical_digest"], build_b["logical_digest"])
            self.assertEqual(build_a["row_counts"], build_b["row_counts"])
            self.assertEqual(build_a["source"]["sha256"], build_b["source"]["sha256"])

    def test_extraction_queue_one_row_at_highest_priority_with_all_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.csv"
            write_catalog(catalog, [
                row(
                    10,
                    "Overlap",
                    "Doe, Jane",
                    "Biography; Essays; Science -- History",
                    "D501; P",
                    "History",
                ),
                row(11, "Tier Two", "Roe, Richard", "", "P", ""),
            ])
            db = root / "books.sqlite"
            build_books(str(catalog), str(db), snapshot_id="queue-fixture")
            connection = sqlite3.connect(db)
            count, distinct_count = connection.execute(
                "SELECT COUNT(*), COUNT(DISTINCT gid) FROM v_extraction_queue"
            ).fetchone()
            self.assertEqual(count, distinct_count)
            priority, tier, reasons, reason_count = connection.execute(
                "SELECT priority, tier, reason_list, reason_count "
                "FROM v_extraction_queue WHERE gid=10"
            ).fetchone()
            self.assertEqual((priority, tier), (10, "tier1"))
            self.assertEqual(reason_count, 4)
            self.assertEqual(
                set(reasons.split("|")),
                {"biography", "core_sections", "essays_letters_speeches", "hold_revisit"},
            )
            self.assertEqual(
                connection.execute(
                    "SELECT tier FROM v_extraction_queue WHERE gid=11"
                ).fetchone()[0],
                "tier2",
            )
            connection.close()


    def test_specific_pz_tier_is_not_promoted_by_broad_language_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.csv"
            write_catalog(catalog, [
                row(20, "Juvenile", "Anonymous [Editor]", "Romance", "PZ", "Children"),
            ])
            database = root / "books.sqlite"
            build_books(str(catalog), str(database), snapshot_id="tier3-fixture")
            connection = sqlite3.connect(database)
            self.assertEqual(
                connection.execute(
                    "SELECT priority, tier, reason_list FROM v_extraction_queue WHERE gid=20"
                ).fetchone(),
                (30, "tier3", "store_only"),
            )
            connection.close()


