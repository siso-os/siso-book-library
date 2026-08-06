from __future__ import annotations

import contextlib
import copy
import gzip
import json
import os
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from support import (
    CATALOG_V1, CATALOG_V2, PAYLOAD_V1, PAYLOAD_V2,
    FIXED_TIME_V1, FIXED_TIME_V2, ROOT, SCRIPTS,
    build_pair, read_ndjson, walk_keys, walk_strings,
)
from booklib.common import ContractError, sha256_file
from build_locator import build as build_locator
from build_release import build_release
from compare_release_summaries import compare
from export_people_graph_observations import (
    export_records, validate_envelope, validate_ndjson, write_ndjson,
)
from pack_payload import pack
from verify_payload import verify


class PayloadAndExportIntegrityTests(unittest.TestCase):
    def test_payload_pack_is_deterministic_and_removes_stale_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "second"
            first_result = pack(PAYLOAD_V1, first, asset_prefix="fixture", max_members=10)
            second_result = pack(PAYLOAD_V1, second, asset_prefix="fixture", max_members=10)
            self.assertEqual(
                first_result["assets"][0]["sha256"], second_result["assets"][0]["sha256"]
            )
            self.assertEqual(first_result["manifest_sha256"], second_result["manifest_sha256"])

            asset = first / "fixture-001.tar"
            with tarfile.open(asset, "r:") as archive, asset.open("rb") as raw:
                members = [member for member in archive if member.isfile()]
                self.assertEqual(
                    [member.name for member in members],
                    ["books/1001.txt.gz", "books/1002.txt.gz", "books/1003.txt.gz"],
                )
                raw.seek(members[0].offset_data)
                gzip_header = raw.read(10)
                self.assertEqual(gzip_header[4:8], b"\x00\x00\x00\x00")

            # Three one-member assets are replaced by one asset; -002 and -003
            # must not remain in the destination.
            pack(PAYLOAD_V1, first, asset_prefix="fixture", max_members=1)
            self.assertTrue((first / "fixture-003.tar").exists())
            pack(PAYLOAD_V2, first, asset_prefix="fixture", max_members=10)
            self.assertEqual(
                sorted(path.name for path in first.glob("fixture-*.tar")),
                ["fixture-001.tar"],
            )

    def test_locator_ranges_checksums_and_container_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload_v1 = root / "payload-v1"
            payload_v2 = root / "payload-v2"
            pack(PAYLOAD_V1, payload_v1, asset_prefix="fixture", max_members=10)
            pack(PAYLOAD_V2, payload_v2, asset_prefix="fixture", max_members=10)
            locator = root / "locator.sqlite"
            build_locator(
                payload_v1 / "fixture-001.tar",
                locator,
                container_name="fixture-001.tar",
                stored_path="payload-v1/fixture-001.tar",
                uri="release://payload/fixture-001.tar",
                indexed_at=FIXED_TIME_V1,
                route="release",
            )
            with contextlib.closing(sqlite3.connect(locator)) as connection:
                self.assertEqual(
                    [row[0] for row in connection.execute("SELECT gid FROM location ORDER BY gid")],
                    [1001, 1002, 1003],
                )

            build_locator(
                payload_v2 / "fixture-001.tar",
                locator,
                container_name="fixture-001.tar",
                stored_path="payload-v2/fixture-001.tar",
                uri="release://payload/fixture-001.tar",
                indexed_at=FIXED_TIME_V2,
                route="release",
            )
            with contextlib.closing(sqlite3.connect(locator)) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute("SELECT * FROM location ORDER BY gid").fetchall()
                self.assertEqual([row["gid"] for row in rows], [1001, 1003, 1004])
                first = rows[0]
            result = verify(locator, asset_root=root)
            self.assertTrue(result["valid"])
            archive = payload_v2 / "fixture-001.tar"
            with archive.open("rb") as handle:
                handle.seek(first["offset"])
                member = handle.read(first["length"])
            self.assertEqual(sha256_file(ROOT / "tests/fixtures/texts_v2/1001.txt"), first["content_sha256"])
            self.assertEqual(gzip.decompress(member), (ROOT / "tests/fixtures/texts_v2/1001.txt").read_bytes())

    def test_observation_export_preserves_roles_and_never_assigns_canonical_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            books, contributors, _, _ = build_pair(root)
            output = root / "observations.ndjson"
            summary = write_ndjson(export_records(books, contributors), output)
            self.assertEqual(summary["records"], 10)
            self.assertEqual(summary["subject_kind_counts"], {"claim": 6, "work": 4})
            self.assertTrue(validate_ndjson(output)["valid"])
            records = read_ndjson(output)
            for record in records:
                keys = set(walk_keys(record))
                self.assertFalse(
                    {"canonical_id", "canonical_person_id", "canonical_entity_id", "person_id"}
                    & keys
                )
                self.assertNotIn(
                    "name", {identifier["scheme"] for identifier in record["identifiers"]}
                )

            work = next(
                record
                for record in records
                if record["subject"]["kind"] == "work"
                and record["subject"]["source_native_id"] == "1001"
            )
            self.assertEqual(
                [item["role"] for item in work["contributions"]], ["author", "translator"]
            )
            self.assertEqual(work["subject"]["attributes"]["payload_rights_state"], "not_restricted_us")
            self.assertIn("Über", work["subject"]["label"])

            institution = next(
                record
                for record in records
                if record["subject"]["kind"] == "claim"
                and record["subject"]["label"] == "Collective of Example City"
            )
            self.assertEqual(
                institution["subject"]["attributes"]["entity_kind_state"], "unknown"
            )
            pseudonym = next(
                record
                for record in records
                if "pseud. River" in record["subject"]["attributes"].get("pseudonym_markers", [])
            )
            self.assertEqual(pseudonym["subject"]["attributes"]["identity_state"], "unresolved")

    def test_envelope_validator_rejects_canonical_and_attribute_identifiers(self):
        with tempfile.TemporaryDirectory() as temporary:
            books, contributors, _, _ = build_pair(Path(temporary))
            base = export_records(books, contributors)[0]
            canonical = copy.deepcopy(base)
            canonical["subject"]["canonical_id"] = "pg:forbidden"
            with self.assertRaises(ContractError):
                validate_envelope(canonical)

            name_identifier = copy.deepcopy(base)
            name_identifier["identifiers"][0]["scheme"] = "name"
            with self.assertRaises(ContractError):
                validate_envelope(name_identifier)

            handle_identifier = copy.deepcopy(base)
            handle_identifier["identifiers"][0].update(
                {
                    "scheme": "handle",
                    "scope": "global",
                    "stability": "stable",
                    "uniqueness": "unique",
                }
            )
            with self.assertRaises(ContractError):
                validate_envelope(handle_identifier)

    def test_compatibility_loader_rejects_apply_without_opening_graph(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = root / "canonical.sqlite"
            graph.write_bytes(b"do-not-touch")
            before = graph.read_bytes()
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "load_into_people_graph.py"),
                    "--graph",
                    str(graph),
                    "--apply",
                ],
                cwd=ROOT,
                env={**os.environ, "PYTHONPATH": str(SCRIPTS)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(process.returncode, 2)
            self.assertEqual(graph.read_bytes(), before)
            self.assertIn('"graph_opened": false', process.stderr)

    def test_full_release_receipt_is_public_safe_and_source_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = build_release(
                source_manifest_path=CATALOG_V1,
                payload_input_manifest_path=PAYLOAD_V1,
                out_dir=root,
                built_at=FIXED_TIME_V1,
                asset_prefix="fixture",
                max_members=10,
            )
            release_path = Path(result["release"]["manifest"])
            release = json.loads(release_path.read_text(encoding="utf-8"))
            self.assertEqual(release["manifest_version"], "book-library-release-1")
            self.assertEqual(
                release["source"]["payload_sha256"],
                "fff72a45518bb4877626825761d38f57ee8e8619b3e222171432065d60b11fe7",
            )
            self.assertEqual(release["rights_coverage"], {"not_restricted_us": 4})
            self.assertTrue(
                release["components"]["locator"]["verification"]["valid"]
            )
            self.assertFalse(release["claims"]["canonical_people_graph_ids_assigned"])
            self.assertFalse(release["claims"]["name_only_identity_merges"])
            temporary_prefix = str(root.resolve())
            self.assertFalse(
                any(value.startswith(temporary_prefix) for value in walk_strings(release))
            )

    def test_full_pipeline_replaces_stale_metadata_payload_and_locator_set(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_release(
                source_manifest_path=CATALOG_V1,
                payload_input_manifest_path=PAYLOAD_V1,
                out_dir=root,
                built_at=FIXED_TIME_V1,
                asset_prefix="fixture",
                max_members=1,
            )
            with contextlib.closing(sqlite3.connect(root / "locator.sqlite")) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM container").fetchone()[0], 3)
            build_release(
                source_manifest_path=CATALOG_V2,
                payload_input_manifest_path=PAYLOAD_V2,
                out_dir=root,
                built_at=FIXED_TIME_V2,
                asset_prefix="fixture",
                max_members=10,
            )
            with contextlib.closing(sqlite3.connect(root / "books.sqlite")) as connection:
                self.assertEqual(
                    [row[0] for row in connection.execute("SELECT gid FROM book ORDER BY gid")],
                    [1001, 1003, 1004],
                )
            with contextlib.closing(sqlite3.connect(root / "locator.sqlite")) as connection:
                self.assertEqual(
                    [row[0] for row in connection.execute("SELECT container FROM container")],
                    ["fixture-001.tar"],
                )
                self.assertEqual(
                    [row[0] for row in connection.execute("SELECT gid FROM location ORDER BY gid")],
                    [1001, 1003, 1004],
                )
            self.assertEqual(
                sorted(path.name for path in (root / "payload").glob("fixture-*.tar")),
                ["fixture-001.tar"],
            )

    def test_release_summary_comparison_uses_logical_receipts(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_result = build_release(
                source_manifest_path=CATALOG_V1,
                payload_input_manifest_path=PAYLOAD_V1,
                out_dir=Path(first),
                built_at=FIXED_TIME_V1,
                asset_prefix="fixture",
                max_members=10,
            )
            second_result = build_release(
                source_manifest_path=CATALOG_V1,
                payload_input_manifest_path=PAYLOAD_V1,
                out_dir=Path(second),
                built_at=FIXED_TIME_V1,
                asset_prefix="fixture",
                max_members=10,
            )
            result = compare(first_result, second_result)
            self.assertTrue(result["equivalent"])
            self.assertEqual(result["mismatches"], {})
            changed = copy.deepcopy(second_result)
            changed["observation_export"]["ndjson_sha256"] = "0" * 64
            mismatch = compare(first_result, changed)
            self.assertFalse(mismatch["equivalent"])
            self.assertIn("observations_ndjson_sha256", mismatch["mismatches"])


if __name__ == "__main__":
    unittest.main()
