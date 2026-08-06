## Parallel lane
Book Library integrity and parallel graph export (Prompt 7)

## Branch
`books/integrity-export-parallel-20260806-2`

## Owned paths
`scripts/**`, `index/**`, new `tests/**`, `manifests/**`, `docs/**`, and
`.github/workflows/book-library-integrity.yml`.

## Behavior changed
- Metadata and contributor indexes rebuild as complete source replacements.
- LoCC parsing retains letter-plus-digit subclasses such as `D5` and `Q1`.
- Extraction queue returns one highest-priority row per Work plus all reasons.
- Book contributors export as source observations, not name-derived people.
- The compatibility loader emits validated `pg-observation-0.1` NDJSON and rejects legacy write flags.
- Payload pack/index/verify tooling reproduces individually gzipped tar members, exact offsets/lengths, and checksums.
- Source, payload, locator, observation, and release receipts are versioned.

## Compatibility preserved
Existing build entry-point names and principal `--csv`, `--db`, `--books`, and
`--people` flags remain. Current index and payload release assets are not modified.
The People Graph can ingest the envelope later without depending on a v3 schema.

## Tests and measurements
- `python3 -m compileall -q scripts tests`
- `python3 -m unittest discover -v`: 13/13 passed.
- `python3 scripts/run_fixture_pipeline.py --work-dir <dir> --clean`: passed.
- Clean-build logical digest: `abc7e01182af081428fe99c63c259e13b3124cf0b648454ffd8ef541f94743a1`.
- Source SHA-256: `83825a3f3a692a34b55610cac29be0eba59c9bf6472ec85e4da11e75c42e739f`.
- Observation export: 10 records, 4 Works, 6 contributor observations, no canonical IDs/name-only merges.
- Payload verification: 4/4 members, zero errors; two packs share tar SHA-256 `3d97cf6a56c63fb782010a5dfcc6cfd40f4a02a1c7b971ce632036b61ad0a2d2`.
- Two complete pipelines in different work directories share aggregate release
  manifest SHA-256 `11e482cd8fbc5bf0991db81b6ac4e285a19a2137c5719395357fbc4fb27c88cd`;
  written receipts contain no work-directory paths.

## External sources and rights
Official Project Gutenberg feed/permission/license pages, the Library of Congress
Classification outline, JSON Schema Draft 2020-12, Python gzip/tar documentation,
and SQLite documentation are recorded in `docs/source-register.md`. Fixtures are
synthetic. No production SQLite, tar, gzip, corpus, credentials, or private paths
are committed or uploaded.

## Integration seams
- Consume `pg-observation-0.1` as observations only.
- Preserve Gutenberg Work IDs and contributor occurrence IDs exactly.
- Never reinterpret `source_label_key` as identity.
- Regenerate released index/locator manifests before claiming the new contracts.
- Review legacy automation that still expects canonical People Graph writes.

## Known risks
- Gutenberg contributor parsing remains source-field specific and replayable from raw rows.
- Contributor order changes upstream create new occurrence IDs by design.
- Byte-identical payloads are scoped to the recorded compression toolchain.
- Full production verification is I/O-intensive and was not run without production assets.
- Existing release assets require later regeneration/re-indexing before promotion.
