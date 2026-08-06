# Parallel handoff — Book Library integrity and graph export

## Scope

Parallel lane: Book Library integrity/export

Branch: `books/integrity-export-parallel-20260806-2`

Base inspected: `sisodias/siso-book-library` `main` at
`be9ab0831b9ea8802d6898f3a3dfa8a61c63e80b`.

This lane makes metadata builds source-replaceable, defines stable logical
receipts, corrects LoCC parsing and queue semantics, adds tracked payload
pack/index/verify tooling, and exports `pg-observation-0.1` without canonical
identity resolution.

## Changed paths

- `scripts/**`: builders, contributor observations, export, payload tooling,
  release receipts, and the one-command fixture pipeline.
- `index/tier_queries.sql`: candidate/reason/one-row queue views.
- `tests/**`: public-safe fixtures and offline invariants.
- `manifests/**`: versioned JSON Schemas.
- `docs/**`: integrity, payload, export, future model, and this handoff.
- `.github/workflows/book-library-integrity.yml`: offline CI.

No production SQLite database, compressed corpus, tar, gzip member, credential,
private path, or rights-unclear payload is included.

## Commands

```bash
python3 -m unittest discover -v
python3 scripts/run_fixture_pipeline.py

# Retain generated fixture receipts outside Git:
python3 scripts/run_fixture_pipeline.py \
  --work-dir /tmp/siso-book-library-fixture --clean
```

Production-shaped commands are documented in `docs/payload-locator.md` and the
individual script help output.

## Tests

The lane-local suite covers:

- LoCC letter+digit and letter subclass parsing;
- whole-snapshot source replacement and timestamp-independent logical digests;
- one queue row per Work, highest-priority selection, and full reason retention;
- specific `PZ` tier behavior;
- role, Unicode, alias, institution, and pseudonym preservation;
- repeated exact names remaining separate contributor observations;
- stale contributor-edge removal;
- envelope validation, no canonical IDs, and no name identifiers;
- deterministic fixture tar packing, exact offsets, compressed/uncompressed
  checksums, and stale locator replacement;
- explicit legacy-locator regeneration;
- public-safe, path-independent release receipt creation.

The full fixture command additionally builds the same catalog twice with different
retrieval timestamps and requires equal logical digest, row counts, and source
hash.

## Assumptions

- The Project Gutenberg CSV `Text#` is the source-native Work/ebook record ID.
- Semicolon remains the upstream repeated-value separator for the catalog fields
  used by the existing code.
- Contributor order is source-native within a Work snapshot; a changed upstream
  order produces changed observations rather than a hidden identity rewrite.
- `pg-observation-0.1` is an interim observation contract, not a canonical
  ontology.
- The closed rights vocabulary applies to the envelope; jurisdiction-specific
  details remain in rights-basis attributes/receipts.

## Compatibility seams

- Existing `build_books_module.py --csv/--db/--rights/--source` flags remain, with
  additional manifest parameters. Unsupported rights-state strings now fail
  rather than being silently generalized.
- Existing `build_people_graph.py --books/--db` remains, but its output semantics
  are source observations, not normalized people.
- Compatibility views named `person` and `person_work` expose one row per
  contributor occurrence; they must not be interpreted as canonical entities.
- `load_into_people_graph.py` remains the old entry-point name but exports NDJSON.
  Old write flags fail explicitly.
- People Graph lanes can consume the NDJSON directly. The comparison-only label
  hash is not an identity key.
- Existing release index databases should be rebuilt; current payload tar files
  can be re-indexed and verified without repacking if their bytes are retained.

## Known risks

- Gutenberg's Authors field can contain edge cases that are not safely split by a
  simple semicolon; raw rows survive for replay and parser revision.
- Contribution order is snapshot-relative, so an upstream reorder changes
  occurrence IDs. The snapshot ID and raw evidence make that change inspectable.
- Payload tar byte determinism is scoped to the same compression toolchain; zlib
  implementations may differ even when logical inputs match.
- The payload verifier reads every compressed member to hash it; full-corpus
  verification is I/O-intensive by design.
- Existing published asset claims were not re-measured in this lane because no
  production assets were downloaded or uploaded.

## Data and rights notes

Tracked fixtures are synthetic and public-safe. Metadata and text rights are
recorded separately. `pending` blocks publication when a reviewed basis is not
available. The tooling does not acquire texts, bypass access controls, upload
assets, or expand the rights granted by a source.

## Suggested merge considerations

1. Review the deliberate breaking semantic change from canonical name writes to
   observation export before merging automation that still passes `--apply`.
2. Merge the queue SQL and builder together so the corrected `section`/`bookcase`
   semantics cannot drift.
3. Regenerate index release assets from a pinned catalog snapshot and compare the
   new row counts/digests before replacing any release download.
4. Re-index and verify all existing tar containers before publishing a locator-v2
   asset; do not partially upgrade a legacy locator.
5. Run the People Graph integration validator against the emitted NDJSON and
   preserve contributor occurrence IDs exactly.
6. Keep this PR independent of any People Graph v3 schema; no other lane is a
   prerequisite.

## Assets requiring later regeneration

- `books.sqlite` / metadata index release asset;
- contributor/people index release asset;
- `locator.sqlite` with per-member SHA-256 and locator-v2 schema;
- public component and aggregate release manifests;
- optionally, payload tars only if existing bytes fail verification or a new
  deterministic pack layout is intentionally adopted.

## Audit trail and exact measured evidence

The branch also tracks:

- `docs/engineering-decision-log.md`: evidence, decisions, alternatives, and proofs;
- `docs/source-register.md`: exact repository revisions and official sources;
- `docs/draft-pr-body.md`: ready-to-use draft PR description with the required fields;
- `docs/validation/2026-08-06-unit-tests.txt`: complete 13-test transcript;
- `docs/validation/2026-08-06-fixture-report.json`: machine-readable digests,
  counts, queue reasons, observation-export metrics, payload checks, and release
  publication state;
- `docs/validation/2026-08-06-path-independence.json`: two-work-directory
  reproducibility and private-path exclusion proof.

Measured clean-build results:

- metadata logical digest: `abc7e01182af081428fe99c63c259e13b3124cf0b648454ffd8ef541f94743a1`;
- contributor logical digest: `ad9c2400d419c754bddde03f3099d2cd5715400a6d471f48e669ef8772d5c863`;
- observation export digest: `1eb9c3a11a341f036433d6549b2a3e442892545146bb01b1d37ac62e10feef18`;
- payload logical digest: `30a9d65f68ebe8f8be4b23500b51da64d481a8dd5b9b34c04ef69a66fc1a9bc4`;
- deterministic fixture tar SHA-256: `3d97cf6a56c63fb782010a5dfcc6cfd40f4a02a1c7b971ce632036b61ad0a2d2`;
- observation rows: 10 total = 4 Works + 6 contributor occurrences;
- payload verification: 4 members checked, zero errors;
- path-independent aggregate release manifest SHA-256:
  `11e482cd8fbc5bf0991db81b6ac4e285a19a2137c5719395357fbc4fb27c88cd`;
- unit tests: 13 passed, zero failures/errors/skips.
