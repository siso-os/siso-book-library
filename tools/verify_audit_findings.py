#!/usr/bin/env python3
"""Reproduce bounded findings from the 2026-08-06 Book Library audit.

The verifier uses only the Python standard library. It inspects checked-in
source and runs the current extraction-profile SQL against a synthetic SQLite
fixture. It reports JSON so later agents can distinguish repaired behavior from
an unverifiable prose claim.

Usage:
    python3 tools/verify_audit_findings.py
    python3 tools/verify_audit_findings.py --strict-current

`--strict-current` is for validating this audit against the original
implementation. It should not become a permanent CI gate because a correct fix
will make a finding no longer reproduce.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]


def read_text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def result(
    check_id: str,
    title: str,
    reproduced: bool,
    evidence: dict[str, Any],
    *,
    finding_id: str | None,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "finding_id": finding_id,
        "title": title,
        "status": "finding_reproduced" if reproduced else "finding_not_reproduced",
        "evidence": evidence,
    }


def check_direct_people_graph_write() -> dict[str, Any]:
    source = read_text("scripts/load_into_people_graph.py")
    evidence = {
        "opens_graph_database": "sqlite3.connect(graph_db)" in source,
        "normalized_name_map": "existing.setdefault(norm(name), pid)" in source,
        "reuses_existing_id": "if nkey in existing" in source and "pid = existing[nkey]" in source,
        "writes_person_rows": "INSERT OR IGNORE INTO person" in source,
        "writes_content_rows": "INSERT OR IGNORE INTO person_content" in source,
    }
    return result(
        "direct_people_graph_write",
        "Book integration writes canonical graph rows and matches by normalized name",
        all(evidence.values()),
        evidence,
        finding_id="BL-P0-001",
    )


def check_locator_digest_contract() -> dict[str, Any]:
    readme = read_text("README.md")
    locator = read_text("scripts/build_locator.py")
    readme_claims_sha = (
        "offset, length, sha256" in readme
        or "(asset, offset, length, sha256)" in readme
    )
    schema_has_sha = "sha256" in locator.lower()
    evidence = {
        "readme_claims_per_book_sha256": readme_claims_sha,
        "checked_in_locator_mentions_sha256": schema_has_sha,
        "locator_records_offset": "offset" in locator,
        "locator_records_length": "length" in locator,
    }
    reproduced = readme_claims_sha and not schema_has_sha
    return result(
        "locator_digest_contract",
        "README claims per-book SHA-256 but the checked-in locator does not store it",
        reproduced,
        evidence,
        finding_id="BL-P0-002",
    )


def check_wall_clock_content() -> dict[str, Any]:
    source = read_text("scripts/build_books_module.py")
    evidence = {
        "uses_current_gmtime": "time.gmtime()" in source,
        "formats_current_time": 'time.strftime("%Y-%m-%dT%H:%M:%SZ"' in source,
        "writes_fetched_at_column": "fetched_at" in source,
        "explicit_observed_at_argument": "--observed-at" in source,
        "source_date_epoch_support": "SOURCE_DATE_EPOCH" in source,
    }
    reproduced = (
        evidence["uses_current_gmtime"]
        and evidence["writes_fetched_at_column"]
        and not evidence["explicit_observed_at_argument"]
        and not evidence["source_date_epoch_support"]
    )
    return result(
        "wall_clock_content",
        "The index builder embeds an unpinned wall clock in content rows",
        reproduced,
        evidence,
        finding_id="BL-P0-003",
    )


def build_tier_fixture() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript(
        """
        CREATE TABLE book (
          gid INTEGER PRIMARY KEY,
          title TEXT NOT NULL,
          authors TEXT,
          issued TEXT,
          media_type TEXT
        );
        CREATE TABLE book_class (
          gid INTEGER NOT NULL,
          locc TEXT NOT NULL,
          section TEXT NOT NULL,
          bookcase TEXT NOT NULL
        );
        CREATE TABLE book_subject (
          gid INTEGER NOT NULL,
          subject TEXT NOT NULL
        );
        """
    )
    # QA belongs to the Science section Q but has bookcase QA.
    con.execute(
        "INSERT INTO book VALUES (1, 'Synthetic QA Book', 'Example', '', 'Text')"
    )
    con.execute("INSERT INTO book_class VALUES (1, 'QA', 'Q', 'QA')")

    # This book qualifies for both the core B section/bookcase and biography.
    con.execute(
        "INSERT INTO book VALUES (2, 'Synthetic Biography', 'Example', '', 'Text')"
    )
    con.execute("INSERT INTO book_class VALUES (2, 'B', 'B', 'B')")
    con.execute("INSERT INTO book_subject VALUES (2, 'Scientists -- Biography')")

    con.executescript(read_text("index/tier_queries.sql"))
    return con


def check_section_bookcase_policy() -> dict[str, Any]:
    con = build_tier_fixture()
    try:
        core_rows = con.execute(
            "SELECT gid, title FROM v_tier1_core ORDER BY gid"
        ).fetchall()
    finally:
        con.close()
    qa_present = any(row[0] == 1 for row in core_rows)
    reproduced = not qa_present
    return result(
        "section_bookcase_policy",
        "A QA book is omitted by a policy described as including the Science section",
        reproduced,
        {
            "fixture": {
                "gid": 1,
                "locc": "QA",
                "section": "Q",
                "bookcase": "QA"
            },
            "v_tier1_core_rows": core_rows,
            "qa_fixture_present": qa_present,
        },
        finding_id="BL-P1-006",
    )


def check_queue_deduplication() -> dict[str, Any]:
    con = build_tier_fixture()
    try:
        # v_extraction_queue no longer exposes a bare `reason` column. The fixed
        # view returns exactly one row per Work at its best tier and aggregates
        # the reasons into reason_list/reason_count, which is what closed
        # BL-P1-007. Probe the aggregated column so this check tests the current
        # schema; the reproduction test below (more rows than distinct gids) is
        # unchanged and still detects the original duplication if it returns.
        rows = con.execute(
            "SELECT tier, reason_list, gid FROM v_extraction_queue WHERE gid=2 ORDER BY reason_list"
        ).fetchall()
        distinct_gid = con.execute(
            "SELECT COUNT(DISTINCT gid) FROM v_extraction_queue WHERE gid=2"
        ).fetchone()[0]
    finally:
        con.close()
    reproduced = len(rows) > distinct_gid
    return result(
        "queue_deduplication",
        "Different reason values preserve several extraction-queue rows for one GID",
        reproduced,
        {
            "queue_rows_for_gid_2": rows,
            "row_count": len(rows),
            "distinct_gid_count": distinct_gid,
        },
        finding_id="BL-P1-007",
    )


def check_source_actor_key_semantics() -> dict[str, Any]:
    source = read_text("scripts/build_people_graph.py")
    evidence = {
        "normalized_name_key": "def person_key" in source,
        "ascii_only_filter": 'r"[^a-z0-9, ]"' in source,
        "name_only_when_dates_missing": "if birth or death" in source,
        "corporate_heuristic": 'if "," not in s and birth is None and death is None' in source,
    }
    reproduced = all(evidence.values())
    return result(
        "source_actor_key_semantics",
        "The source actor key is a lossy heuristic, not safe canonical identity",
        reproduced,
        evidence,
        finding_id="BL-P1-009",
    )


def check_packaging_pipeline_presence() -> dict[str, Any]:
    scripts = sorted(path.name for path in (ROOT / "scripts").glob("*.py"))
    packaging_markers = (
        "pack_payload",
        "build_payload",
        "publish_payload",
        "release_payload",
    )
    packaging_scripts = [
        name for name in scripts if any(marker in name for marker in packaging_markers)
    ]
    locator_present = "build_locator.py" in scripts
    reproduced = locator_present and not packaging_scripts
    return result(
        "packaging_pipeline_presence",
        "A locator exists but no checked-in payload packager is discoverable by filename",
        reproduced,
        {
            "scripts": scripts,
            "packaging_scripts_detected": packaging_scripts,
            "locator_script_present": locator_present,
            "note": "Filename inspection is a bounded repository check, not proof that no unpublished external process exists."
        },
        finding_id="BL-P1-010",
    )


def check_test_contract_presence() -> dict[str, Any]:
    tests_dir = ROOT / "tests"
    workflows_dir = ROOT / ".github" / "workflows"
    test_files = sorted(
        str(path.relative_to(ROOT)) for path in tests_dir.rglob("*") if path.is_file()
    ) if tests_dir.exists() else []
    workflow_files = sorted(
        str(path.relative_to(ROOT))
        for path in workflows_dir.rglob("*")
        if path.is_file()
    ) if workflows_dir.exists() else []
    reproduced = not test_files and not workflow_files
    return result(
        "test_contract_presence",
        "No checked-in tests or GitHub Actions workflows are present",
        reproduced,
        {
            "test_files": test_files,
            "workflow_files": workflow_files,
        },
        finding_id="BL-P1-013",
    )


def run_checks() -> list[dict[str, Any]]:
    checks: list[Callable[[], dict[str, Any]]] = [
        check_direct_people_graph_write,
        check_locator_digest_contract,
        check_wall_clock_content,
        check_section_bookcase_policy,
        check_queue_deduplication,
        check_source_actor_key_semantics,
        check_packaging_pipeline_presence,
        check_test_contract_presence,
    ]
    output: list[dict[str, Any]] = []
    for check in checks:
        try:
            output.append(check())
        except Exception as exc:
            output.append(
                {
                    "check_id": check.__name__,
                    "finding_id": None,
                    "title": "Audit check raised an exception",
                    "status": "error",
                    "evidence": {
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                    },
                }
            )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict-current",
        action="store_true",
        help="Fail if a documented current finding is not reproduced."
    )
    args = parser.parse_args()

    checks = run_checks()
    summary = {
        "finding_reproduced": sum(c["status"] == "finding_reproduced" for c in checks),
        "finding_not_reproduced": sum(
            c["status"] == "finding_not_reproduced" for c in checks
        ),
        "errors": sum(c["status"] == "error" for c in checks),
    }
    report = {
        "audit_id": "siso-book-library-first-principles-2026-08-06",
        "repository_root": str(ROOT),
        "summary": summary,
        "checks": checks,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if summary["errors"]:
        return 2
    if args.strict_current and summary["finding_not_reproduced"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
