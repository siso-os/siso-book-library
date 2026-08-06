#!/usr/bin/env python3
"""Run the complete offline integrity/export pipeline against tracked fixtures."""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

try:
    from scripts.build_books_module import build as build_books
    from scripts.build_people_graph import build as build_contributors
    from scripts.create_release_manifest import create as create_release_manifest
    from scripts.export_people_graph_observations import export as export_observations
    from scripts.pack_payload import pack
    from scripts.verify_payload import verify
    from scripts.common import public_receipt, write_public_receipt_atomic
except ModuleNotFoundError:  # direct execution from scripts/
    from build_books_module import build as build_books  # type: ignore
    from build_people_graph import build as build_contributors  # type: ignore
    from create_release_manifest import create as create_release_manifest  # type: ignore
    from export_people_graph_observations import export as export_observations  # type: ignore
    from pack_payload import pack  # type: ignore
    from verify_payload import verify  # type: ignore
    from common import public_receipt, write_public_receipt_atomic  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def _prepare_output(path: Path, clean: bool) -> None:
    if path.exists() and any(path.iterdir()):
        if not clean:
            raise FileExistsError(
                f"output directory is not empty: {path}; pass --clean to replace it"
            )
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _assert_source_replacement(database: Path) -> dict[str, object]:
    connection = sqlite3.connect(database)
    try:
        gids = [int(row[0]) for row in connection.execute("SELECT gid FROM book ORDER BY gid")]
        stale_subjects = int(connection.execute(
            "SELECT COUNT(*) FROM book_subject WHERE subject LIKE 'Stale%'"
        ).fetchone()[0])
        stale_shelves = int(connection.execute(
            "SELECT COUNT(*) FROM book_shelf WHERE shelf LIKE 'Stale%'"
        ).fetchone()[0])
        stale_classes = int(connection.execute(
            "SELECT COUNT(*) FROM book_class WHERE gid = 3"
        ).fetchone()[0])
    finally:
        connection.close()
    if 3 in gids or stale_subjects or stale_shelves or stale_classes:
        raise AssertionError("source replacement left stale metadata rows")
    return {
        "gids": gids,
        "stale_subjects": stale_subjects,
        "stale_shelves": stale_shelves,
        "stale_classes": stale_classes,
    }


def _queue_measurements(database: Path) -> dict[str, object]:
    connection = sqlite3.connect(database)
    try:
        count, distinct_count = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT gid) FROM v_extraction_queue"
        ).fetchone()
        rows = [
            {
                "gid": int(gid),
                "priority": int(priority),
                "tier": str(tier),
                "reasons": str(reasons).split("|") if reasons else [],
            }
            for gid, priority, tier, reasons in connection.execute(
                """SELECT gid, priority, tier, reason_list
                   FROM v_extraction_queue ORDER BY gid"""
            )
        ]
    finally:
        connection.close()
    if count != distinct_count:
        raise AssertionError("extraction queue contains more than one row per Work")
    return {"rows": int(count), "distinct_works": int(distinct_count), "items": rows}


def _contributor_measurements(database: Path) -> dict[str, object]:
    connection = sqlite3.connect(database)
    try:
        repeated = connection.execute(
            """SELECT COUNT(*), COUNT(DISTINCT contributor_observation_id),
                      COUNT(DISTINCT source_label_key)
               FROM source_contributor
               WHERE source_label = 'Doe, Jane [Author]'"""
        ).fetchone()
        roles = [
            str(row[0])
            for row in connection.execute(
                "SELECT role FROM contribution ORDER BY gid, contribution_order"
            )
        ]
        unicode_count = int(connection.execute(
            "SELECT COUNT(*) FROM source_contributor WHERE source_label LIKE '平塚%'"
        ).fetchone()[0])
        unresolved_count = int(connection.execute(
            "SELECT COUNT(*) FROM source_contributor WHERE entity_kind_state='unresolved'"
        ).fetchone()[0])
    finally:
        connection.close()
    if repeated != (2, 2, 1):
        raise AssertionError(
            "repeated exact labels must remain two observations sharing one comparison key"
        )
    if unicode_count != 1:
        raise AssertionError("Unicode contributor label was not preserved")
    return {
        "repeated_exact_label": {
            "occurrences": int(repeated[0]),
            "distinct_observations": int(repeated[1]),
            "comparison_keys": int(repeated[2]),
        },
        "roles": roles,
        "unicode_labels": unicode_count,
        "unresolved_entity_kind_rows": unresolved_count,
    }


def run(output_dir: Path, clean: bool = False) -> dict[str, object]:
    _prepare_output(output_dir, clean)
    current_csv = FIXTURES / "pg_catalog_v2.csv"
    previous_csv = FIXTURES / "pg_catalog_v1.csv"
    texts = FIXTURES / "texts"

    build_a_dir = output_dir / "build-a"
    build_b_dir = output_dir / "build-b"
    build_a_dir.mkdir()
    build_b_dir.mkdir()
    books_a = build_a_dir / "books.sqlite"
    books_b = build_b_dir / "books.sqlite"
    books_a_manifest = build_a_dir / "books-manifest.json"
    books_b_manifest = build_b_dir / "books-manifest.json"

    common = {
        "snapshot_id": "fixture-v2",
        "terms_revision": "fixture-terms-v1",
        "rights": "public_metadata",
        "rights_basis": "synthetic catalog fixture; no production text-rights claim",
        "acquisition_method": "tracked_offline_fixture",
    }
    build_a = build_books(
        str(current_csv), str(books_a),
        retrieved_at="2026-08-06T00:00:00Z",
        observed_at="2026-08-06T00:00:00Z",
        manifest_out=str(books_a_manifest),
        **common,
    )
    build_b = build_books(
        str(current_csv), str(books_b),
        retrieved_at="2026-09-01T12:34:56Z",
        observed_at="2026-09-01T12:34:56Z",
        manifest_out=str(books_b_manifest),
        **common,
    )
    if build_a["logical_digest"] != build_b["logical_digest"]:
        raise AssertionError("clean fixture builds produced different logical digests")
    if build_a["row_counts"] != build_b["row_counts"]:
        raise AssertionError("clean fixture builds produced different row counts")
    if build_a["source"]["sha256"] != build_b["source"]["sha256"]:  # type: ignore[index]
        raise AssertionError("clean fixture builds produced different source hashes")

    replacement_dir = output_dir / "source-replacement"
    replacement_dir.mkdir()
    replacement_db = replacement_dir / "books.sqlite"
    build_books(
        str(previous_csv), str(replacement_db), snapshot_id="fixture-v1",
        retrieved_at="2026-08-05T00:00:00Z",
        terms_revision="fixture-terms-v1",
        rights="public_metadata",
    )
    build_books(
        str(current_csv), str(replacement_db), snapshot_id="fixture-v2",
        retrieved_at="2026-08-06T00:00:00Z",
        terms_revision="fixture-terms-v1",
        rights="public_metadata",
    )
    replacement = _assert_source_replacement(replacement_db)
    queue = _queue_measurements(books_a)

    contributors_db = build_a_dir / "contributors.sqlite"
    contributors_manifest = build_a_dir / "contributors-manifest.json"
    contributors = build_contributors(
        str(books_a), str(contributors_db), str(contributors_manifest)
    )
    contributor_checks = _contributor_measurements(contributors_db)

    observations = build_a_dir / "book-library-observations.ndjson"
    observations_manifest = build_a_dir / "observations-manifest.json"
    observation_export = export_observations(
        str(books_a), str(contributors_db), str(observations),
        str(observations_manifest),
    )

    payload_dir = output_dir / "payload"
    payload_dir.mkdir()
    payload_tar = payload_dir / "fixture-books.tar"
    payload_tar_second = payload_dir / "fixture-books-second.tar"
    payload_manifest = payload_dir / "payload-manifest.json"
    payload_manifest_second = payload_dir / "payload-manifest-second.json"
    locator_db = payload_dir / "locator.sqlite"
    locator_manifest = payload_dir / "locator-manifest.json"
    payload = pack(
        str(texts), str(payload_tar), str(payload_manifest),
        locator_db=str(locator_db),
        locator_manifest_out=str(locator_manifest),
        container_name="fixture-books",
        source_id="synthetic_fixture_text",
        snapshot_id="fixture-v2",
        retrieved_at="2026-08-06T00:00:00Z",
        terms_revision="fixture-terms-v1",
        rights_state="open_data",
        rights_basis="synthetic fixture text authored for repository tests",
    )
    payload_second = pack(
        str(texts), str(payload_tar_second), str(payload_manifest_second),
        container_name="fixture-books",
        source_id="synthetic_fixture_text",
        snapshot_id="fixture-v2",
        retrieved_at="2026-09-01T12:34:56Z",
        terms_revision="fixture-terms-v1",
        rights_state="open_data",
        rights_basis="synthetic fixture text authored for repository tests",
    )
    if payload["tar_sha256"] != payload_second["tar_sha256"]:
        raise AssertionError("deterministic fixture payload packs differ")
    payload_verification = verify(
        str(payload_tar), str(locator_db), "fixture-books", str(payload_manifest)
    )
    if not payload_verification["ok"]:
        raise AssertionError(payload_verification["errors"])

    release_manifest_path = output_dir / "release-manifest.json"
    release = create_release_manifest(
        [
            str(books_a_manifest),
            str(contributors_manifest),
            str(observations_manifest),
            str(payload_manifest),
            str(locator_manifest),
        ],
        str(release_manifest_path),
        "fixture-integrity-export-v1",
        "2026-08-06T00:00:00Z",
    )

    report: dict[str, object] = {
        "report_version": "book-library-fixture-integrity-1",
        "status": "pass",
        "clean_builds": {
            "logical_digest": build_a["logical_digest"],
            "row_counts": build_a["row_counts"],
            "source_sha256": build_a["source"]["sha256"],  # type: ignore[index]
            "different_retrieval_timestamps": True,
        },
        "source_replacement": replacement,
        "extraction_queue": queue,
        "contributors": {
            "logical_digest": contributors["logical_digest"],
            "row_counts": contributors["row_counts"],
            **contributor_checks,
        },
        "observation_export": public_receipt(observation_export),
        "payload": {
            "logical_digest": payload["logical_digest"],
            "tar_sha256": payload["tar_sha256"],
            "second_tar_sha256": payload_second["tar_sha256"],
            "row_counts": payload["row_counts"],
            "verification": payload_verification,
        },
        "release_manifest": {
            "manifest_sha256": release["manifest_sha256"],
            "publication_state": release["publication_state"],
        },
        "commands": [
            "python3 -m unittest discover -v",
            "python3 scripts/run_fixture_pipeline.py --work-dir <dir> --clean",
        ],
        "generated_assets_are_fixtures_only": True,
    }
    write_public_receipt_atomic(output_dir / "fixture-report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir")
    parser.add_argument("--clean", action="store_true")
    arguments = parser.parse_args()
    if arguments.work_dir:
        report = run(Path(arguments.work_dir), arguments.clean)
    else:
        with tempfile.TemporaryDirectory(prefix="book-library-fixture-") as directory:
            report = run(Path(directory), clean=False)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
