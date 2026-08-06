# Parallel handoff: Book Library integrity and graph export

## Scope

Implemented Prompt 7 on branch `books/integrity-export-parallel-20260806` from
Book Library main commit `be9ab0831b9ea8802d6898f3a3dfa8a61c63e80b`.
The lane makes metadata/contributor builds source-replaceable, corrects LCC and
queue contracts, adds deterministic payload/locator tooling, and replaces direct
name-based canonical mutation with validated `pg-observation-0.1` export.

No production database, payload corpus, release asset, credential, or private
path is included.

## Changed paths

- `scripts/booklib/**` — common contract, hashing, atomic replacement, logical
  SQLite snapshot helpers
- `scripts/build_books_module.py` — source-manifest build and corrected LCC
- `scripts/build_people_graph.py` — source occurrence contributor graph
- `scripts/export_people_graph*.py` — observation exporter and compatibility
- `scripts/load_into_people_graph.py` — fail-closed retired direct loader
- `scripts/pack_payload.py`, `scripts/build_locator.py`,
  `scripts/verify_payload.py` — tracked payload/range/checksum chain
- `scripts/build_release*.py`, `scripts/logical_digest.py`,
  `scripts/compare_release_summaries.py` — release receipt and equivalence tools
- `index/tier_queries.sql` — one Work per queue row with audited reasons
- `tests/**` — two complete tiny snapshots and 13 offline contract tests
- `manifests/**` — fixture/example manifests and JSON Schemas
- `.github/workflows/book-integrity.yml` — Python 3.11/3.13 offline CI
- `docs/**` — task, audit, rationale, contracts, operations, sources, future
  bibliographic bridge, verification transcript, and this handoff

`README.md` and generated assets are intentionally untouched.

## Behavior changed

1. A metadata or contributor build is now an exact projection of one declared
   source snapshot. It builds into a fresh database and atomically replaces the
   target after validation, so removed upstream rows and edges cannot linger.
2. LCC values store full normalized code, one-letter section, alphabetic
   subclass (`bookcase` compatibility column), and numeric stem. `D501` maps to
   D / D / 501; `PR6019` maps to P / PR / 6019.
3. `v_extraction_queue` returns exactly one row per Work at the best tier, plus
   ordered winning and all-rule reason lists.
4. Contributor rows are source attribution occurrences, not canonical people.
   Roles/order/aliases/Unicode/pseudonym and life-date evidence survive intact.
5. Direct graph mutation by normalized name is retired. `--apply` fails before
   the graph is opened; the safe output is validated `pg-observation-0.1` NDJSON.
6. Payload tooling now creates deterministic per-book gzip members in
   uncompressed tar assets, indexes exact compressed ranges and both hashes, and
   rereads/verifies every range before a release receipt is produced.
7. SQLite reproducibility is stated as logical equivalence. Binary hashes are
   receipts, not cross-platform guarantees.

## Compatibility preserved

- Historical `book` columns remain available for existing read queries.
- Existing edge table names remain.
- `book_class.bookcase` remains present, with clarified subclass semantics.
- `person` and `person_work` remain compatibility views, now explicitly over
  non-canonical source occurrences.
- Legacy command names remain, but unsafe mutation fails closed.
- The People Graph consumes a schema-independent envelope rather than importing
  Book Library SQLite internals.

## Commands

Run all offline tests:

```bash
PYTHONPATH=scripts python3 -Werror::ResourceWarning \
  -m unittest discover -s tests -v
```

Build one complete tiny release:

```bash
PYTHONPATH=scripts python3 scripts/build_release.py \
  --source-manifest manifests/fixtures/catalog-v1.json \
  --payload-input-manifest manifests/fixtures/payload-v1.json \
  --out-dir /tmp/book-library-v1 \
  --built-at 2026-08-06T00:10:00Z \
  --asset-prefix fixture \
  --max-members 10
```

Compare two clean build summaries:

```bash
python3 scripts/compare_release_summaries.py \
  /tmp/build-a/summary.json /tmp/build-b/summary.json
```

Validate an export:

```bash
PYTHONPATH=scripts python3 scripts/validate_observation_export.py \
  /tmp/book-library-v1/people-graph-observations.ndjson
```

The complete command/output transcript is in
`docs/workings/verification-2026-08-06.txt`.

## Tests and measurements

Test result: **13/13 passed offline** on Python 3.13.5 with
`ResourceWarning` promoted to errors. CI repeats compile/tests and clean-build
comparison on Python 3.11 and 3.13.

Fixture-v1 clean-build receipts (two independent directories, equal):

- source CSV SHA-256:
  `fff72a45518bb4877626825761d38f57ee8e8619b3e222171432065d60b11fe7`
- Books logical SHA-256:
  `2076314adb8310d6b33173b11d0452afda9841abac68209dc77dd77d18726d73`
- contributor observations logical SHA-256:
  `120be5f343325682cca6ab34b696277ef2b6a511aad03a1adc5757d99a144022`
- People Graph NDJSON SHA-256:
  `83a1c27b07da699ff18b13b1e7707f9ab38f21f4c9926f2b7549c43456a5027e`
- records: 10 (`work`: 4, `claim`: 6)
- payload manifest SHA-256:
  `47fca93092b5775320beba60378b0ab712b28857e20eb454b4e2cea02c1dc07e`
- payload asset SHA-256:
  `e2974a26c1d3865857fa477fdefe6d0ec1116e38e308e03655353a495e1acc55`
  (3 members, 10,240 bytes)
- locator logical SHA-256:
  `04b69ae91a826c0a50857dff81a46796caec8e1ae326685fd2b03d60d4723bec`
- release manifest SHA-256:
  `cf1bdc843bb860cfe9abab6f1e91d3cbf90a574d3a44f5f92c248affbd6b0077`
- exact range verification: 1 container / 3 members / valid
- rights coverage: `not_restricted_us: 4` (fixture literal, jurisdiction-narrow)

Changed-source v1→v2 proof:

- remaining Work/contributor/locator IDs: `1001`, `1003`, `1004`
- removed Work `1002`, non-text item `1005`, old `Legacy Field`, old roles,
  payload members, and stale containers are absent
- v2 roles are exactly `editor`, `translator`
- one payload asset and one locator container remain

## Assumptions

- Each declared catalog input is a complete snapshot, so full projection
  replacement is the safest reconciliation policy.
- Project Gutenberg `Text#` is stable within that source; it identifies a source
  Work/item, not an abstract bibliographic Work across sources.
- Catalog contributor order is meaningful as an attribution occurrence locator
  within a snapshot, but does not identify a person.
- `book.issued` is the Project Gutenberg release date, not original print date.
- The narrow rights classifier never broadens a literal U.S.-specific source
  statement to worldwide public domain.
- Logical SQLite equality, not binary equality, is the portable build contract.

## Compatibility seams

- **People Graph importer:** consume `pg-observation-0.1`; preserve source facts
  independently from identity candidates/decisions. Map `claim` attribution
  records to a first-class contribution occurrence when that schema exists.
- **v3 bibliographic model:** map Gutenberg item to Digital Item; add
  evidence-backed Work/Expression/Edition links without rewriting this source
  observation.
- **Modern books:** Open Library author/Work/Edition keys and Crossref DOI/ORCID/
  ROR values enter as source-native observations. Name/title similarity remains
  review-only.
- **Incremental acquisition:** an append/delta source can be added later, but its
  materialized snapshot must satisfy the same exact-projection and logical-digest
  contract.
- **Release plane:** generated assets belong in governed release storage, never
  Git history.

## Known risks

- The full 79k-Work production corpus was not downloaded or rebuilt in this PR;
  scale/runtime/asset partitioning still require a governed full-data run.
- The payload packer partitions by member count, not a hard byte ceiling. A
  production run must select/measure partitioning so every release asset stays
  under the chosen host limit.
- Logical SQLite hashing orders every table by all columns. It is correct for the
  fixture and expected current scale but full-build memory/disk/runtime should be
  measured before setting a release SLO.
- Contributor parsing follows the catalog's semicolon-separated string and
  bracketed role conventions. Unusual source syntax remains visible in raw
  labels, but may need a source-versioned parser extension.
- Entity kind remains unresolved unless literal evidence supports a candidate.
  This intentionally reduces automatic recall to protect precision.
- `claim` is an interim envelope subject kind for attribution occurrences; a
  future integration layer may use a more precise table/type.
- Existing published assets and canonicalized Book-person derivatives remain
  under the old contract until explicitly regenerated and reviewed.

## Data and rights notes

- Tests contain only tiny synthetic public-safe metadata/text fixtures.
- No production catalog, full text, SQLite, tar, gzip, credential, or private
  path is committed.
- Metadata source rights and payload rights are tracked separately.
- Per-Work literal rights are retained; normalized rights states are deliberately
  narrow and may remain `pending`.
- The source evidence ledger records official Project Gutenberg, Library of
  Congress, Open Library, and Crossref documentation checked on 2026-08-06.
- No third-party code was copied.

## Suggested merge considerations

1. Review the identity boundary first; do not restore direct name-based mutation.
2. Merge this lane before regenerating Book Library release assets, otherwise
   assets and locator receipts will remain contract-incompatible.
3. Regenerate metadata DB, contributor DB, observation NDJSON, payload tar set,
   locator DB, and release manifest as one coherent release; do not mix old and
   new components.
4. Run the full-data build in external storage, record performance and asset
   sizes, and review rights coverage before upload.
5. Let the People Graph integration lane validate the envelope and decide how
   unresolved attribution claims map into its additive schema; it must not infer
   accepted identity from this export.
