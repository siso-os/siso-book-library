from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.build_locator import build as build_locator
from scripts.create_release_manifest import create as create_release_manifest
from scripts.pack_payload import pack
from scripts.verify_payload import verify

class PayloadAndReleaseTests(unittest.TestCase):
    def test_deterministic_pack_offsets_checksums_and_locator_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "texts"
            inputs.mkdir()
            (inputs / "1.txt").write_text("alpha\n", encoding="utf-8")
            (inputs / "2.txt").write_text("beta\n", encoding="utf-8")
            first_tar = root / "first.tar"
            second_tar = root / "second.tar"
            first_manifest = root / "first.json"
            second_manifest = root / "second.json"
            locator = root / "locator.sqlite"
            first = pack(
                str(inputs), str(first_tar), str(first_manifest),
                locator_db=str(locator), container_name="fixture",
            )
            second = pack(str(inputs), str(second_tar), str(second_manifest))
            self.assertEqual(first["tar_sha256"], second["tar_sha256"])
            written_payload = json.loads(first_manifest.read_text(encoding="utf-8"))
            self.assertNotIn("tar", written_payload)
            self.assertTrue(
                all("source_path" not in member for member in written_payload["members"])
            )
            self.assertNotIn("tar", written_payload["locator"])
            self.assertNotIn("database", written_payload["locator"])
            self.assertNotIn(str(root), first_manifest.read_text(encoding="utf-8"))
            connection = sqlite3.connect(locator)
            rows = connection.execute(
                "SELECT gid, offset, length, payload_sha256 FROM location "
                "WHERE container='fixture' AND route='local' ORDER BY gid"
            ).fetchall()
            self.assertEqual([row[0] for row in rows], [1, 2])
            self.assertTrue(all(row[1] % 512 == 0 for row in rows))
            self.assertTrue(all(row[2] > 0 and len(row[3]) == 64 for row in rows))
            connection.close()
            result = verify(str(first_tar), str(locator), "fixture", str(first_manifest))
            self.assertTrue(result["ok"], result["errors"])

            (inputs / "2.txt").unlink()
            replacement_manifest = root / "replacement.json"
            pack(
                str(inputs), str(first_tar), str(replacement_manifest),
                locator_db=str(locator), container_name="fixture",
            )
            connection = sqlite3.connect(locator)
            self.assertEqual(
                connection.execute(
                    "SELECT gid FROM location WHERE container='fixture' AND route='local'"
                ).fetchall(),
                [(1,)],
            )
            connection.close()
            replacement_result = verify(
                str(first_tar), str(locator), "fixture", str(replacement_manifest)
            )
            self.assertTrue(replacement_result["ok"], replacement_result["errors"])


    def test_legacy_locator_schema_requires_explicit_regeneration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "texts"
            inputs.mkdir()
            (inputs / "1.txt").write_text("alpha\n", encoding="utf-8")
            archive = root / "fixture.tar"
            manifest = root / "payload.json"
            pack(str(inputs), str(archive), str(manifest))
            locator = root / "legacy-locator.sqlite"
            connection = sqlite3.connect(locator)
            connection.executescript(
                """
                CREATE TABLE container (
                  container TEXT PRIMARY KEY, path TEXT NOT NULL, bytes INTEGER,
                  members INTEGER, indexed_at TEXT NOT NULL
                );
                CREATE TABLE location (
                  gid INTEGER, container TEXT, member TEXT, offset INTEGER,
                  length INTEGER, encoding TEXT, route TEXT, uri TEXT, indexed_at TEXT
                );
                """
            )
            connection.close()
            with self.assertRaisesRegex(RuntimeError, "regenerate it into a fresh file"):
                build_locator(str(archive), str(locator), "fixture")

    def test_release_manifest_records_component_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            component = root / "books.json"
            component.write_text(json.dumps({
                "manifest_version": "book-library-build-1",
                "logical_digest": "a" * 64,
                "row_counts": {"book": 2},
                "loader_version": "fixture-loader",
                "schema_version": "fixture-schema",
                "source": {
                    "source_id": "project_gutenberg",
                    "snapshot_id": "fixture",
                    "sha256": "b" * 64,
                    "rights_state": "public_metadata",
                },
            }), encoding="utf-8")
            output = root / "release.json"
            release = create_release_manifest(
                [str(component)], str(output), "fixture-release",
                "2026-08-06T00:00:00Z",
            )
            self.assertEqual(release["publication_state"], "manifest_only_no_assets_uploaded")
            self.assertEqual(release["components"][0]["row_counts"], {"book": 2})
            self.assertEqual(
                len(release["components"][0]["component_receipt_sha256"]), 64
            )
            self.assertNotIn("manifest_file_sha256", release["components"][0])
            self.assertEqual(len(release["manifest_sha256"]), 64)

    def test_release_receipt_is_independent_of_local_paths_and_formatting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            releases = []
            for name, formatting_indent in (("checkout-a", None), ("checkout-b", 4)):
                checkout = root / name
                checkout.mkdir()
                component = checkout / "books.json"
                value = {
                    "manifest_version": "book-library-build-1",
                    "logical_digest": "a" * 64,
                    "row_counts": {"book": 2},
                    "loader_version": "fixture-loader",
                    "schema_version": "fixture-schema",
                    "database": str(checkout / "private" / "books.sqlite"),
                    "output": str(checkout / "private" / "observations.ndjson"),
                    "tar": str(checkout / "private" / "payload.tar"),
                    "source": {
                        "source_id": "project_gutenberg",
                        "snapshot_id": "fixture",
                        "sha256": "b" * 64,
                        "rights_state": "public_metadata",
                    },
                }
                component.write_text(
                    json.dumps(value, indent=formatting_indent, sort_keys=True),
                    encoding="utf-8",
                )
                output = checkout / "release.json"
                release = create_release_manifest(
                    [str(component)], str(output), "fixture-release",
                    "2026-08-06T00:00:00Z",
                )
                releases.append((release, output.read_text(encoding="utf-8"), checkout))

            self.assertEqual(releases[0][0], releases[1][0])
            self.assertEqual(
                releases[0][0]["manifest_sha256"],
                releases[1][0]["manifest_sha256"],
            )
            for release, text, checkout in releases:
                self.assertNotIn(str(checkout), text)
                self.assertNotIn("manifest_file_sha256", text)
                self.assertEqual(
                    len(release["components"][0]["component_receipt_sha256"]),
                    64,
                )


