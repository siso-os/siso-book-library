# Source register — Prompt 7

Retrieved or inspected on 2026-08-06 unless stated otherwise. Sources are split
between binding program inputs, repository evidence, and external technical/
rights references. No third-party code was copied.

## Binding program input

| Source | Exact locator | Use |
| --- | --- | --- |
| Parallel agent prompt set | Uploaded `Pasted text.txt`, Prompt 7 | Branch, path ownership, invariants, acceptance criteria, and `pg-observation-0.1` contract |

## Repository evidence

| Repository | Exact revision | Paths/claims used |
| --- | --- | --- |
| `sisodias/siso-book-library` | `be9ab0831b9ea8802d6898f3a3dfa8a61c63e80b` | Current builders, queue SQL, README payload description, and legacy Book-to-People loader behavior |
| `sisodias/siso-people-graph` | `de048bb3b34bf931b56fd741cb46c1334acdfb98` | `schema/people_schema_v2.sql`: canonical person rows, `external_ids`, `person_content`, `identity_claim`, role-on-edge intent, provenance fields, and stored `rank_score` |
| `sisodias/great-library-of-siso` | `12f4cc249b2b5dc268d05d1698fe9c5e3079327d` | Read-only program context; no files copied and no registry paths changed |

At the Book Library inspection point, the repository had no open pull requests.
The implementation does not depend on another lane or unmerged schema.

## Official external references

| Authority | Locator | What it supports |
| --- | --- | --- |
| Project Gutenberg | `https://www.gutenberg.org/cache/epub/feeds/` | Official catalog feed directory containing `pg_catalog.csv` |
| Project Gutenberg | `https://www.gutenberg.org/policy/permission.html` | Permission, linking, trademark, copyrighted-item, and jurisdiction caveats |
| Project Gutenberg | `https://www.gutenberg.org/policy/license` | Source license/terms context and item-specific restrictions |
| Library of Congress | `https://www.loc.gov/aba/cataloging/classification/lcco/` | Official top-level Library of Congress Classification classes and subclass outlines |
| JSON Schema | `https://json-schema.org/draft/2020-12` | Metaschema and contract version used by tracked JSON Schemas |
| Python documentation | `https://docs.python.org/3/library/gzip.html` | `mtime=0` reproducible gzip behavior and toolchain caveats |
| Python documentation | `https://docs.python.org/3/library/tarfile.html` | USTAR support and tar member/block model used for offsets |
| SQLite documentation | `https://www.sqlite.org/atomiccommit.html` | Atomic commit model informing build-then-replace behavior |
| SQLite documentation | `https://www.sqlite.org/foreignkeys.html` | Foreign-key validation and cascade expectations used by builders/tests |

## Evidence generated in this branch

| Artifact | Purpose |
| --- | --- |
| `tests/fixtures/**` | Tiny public-safe catalog and text inputs |
| `tests/test_integrity.py` | Executable source replacement, LoCC, queue, identity/export, payload, and release invariants |
| `tests/test_manifest_contracts.py` | Tracked schema parse/identity checks |
| `docs/validation/2026-08-06-unit-tests.txt` | Exact offline unit-test transcript |
| `docs/validation/2026-08-06-fixture-report.json` | Exact clean-build digests, counts, queue results, export metrics, payload verification, and publication state |
| `docs/engineering-decision-log.md` | Evidence-to-decision rationale and rejected alternatives |

## Rights and reuse note

The external references establish source behavior and policy context; they do not
turn every payload into an unrestricted global corpus. The implementation records
source-specific rights state and basis, defaults unresolved publication work to a
reviewable state, and commits only synthetic fixture text.
