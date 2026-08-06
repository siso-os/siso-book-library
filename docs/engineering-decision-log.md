# Engineering decision log — Prompt 7

This file records the reviewable engineering rationale for the Book Library
integrity/export lane. It is intentionally an evidence-and-decision record, not
private model scratch work. Another engineer should be able to reproduce every
conclusion from the cited repository state, tracked fixtures, commands, and
invariants below.

## Baseline and operating constraints

- Repository: `sisodias/siso-book-library`
- Base branch: `main`
- Exact base commit inspected: `be9ab0831b9ea8802d6898f3a3dfa8a61c63e80b`
- Implementation branch: `books/integrity-export-parallel-20260806-2`
- Open pull requests at the inspection point on 2026-08-06: none.
- Owned paths: `scripts/**`, `index/**`, new `tests/**`, `manifests/**`,
  `docs/**`, and `.github/workflows/**`.
- `README.md` and unrelated root configuration were not changed.
- Production SQLite databases, payload archives, compressed corpus members,
  credentials, private paths, and rights-unclear payloads are excluded.

The source requirement is Prompt 7 in `Pasted text.txt`: operate independently,
make rebuild and export contracts honest, emit `pg-observation-0.1`, preserve
roles/Unicode/pseudonyms/institutions, and publish only code plus tiny public-safe
fixtures.

## Evidence inspected before implementation

1. Current Book Library builders and queue SQL at the exact base commit.
2. The People Graph v2 schema at
   `sisodias/siso-people-graph@de048bb3b34bf931b56fd741cb46c1334acdfb98`,
   especially `person`, `external_ids`, `person_content`, `identity_claim`,
   `person_topic`, and `rank_score`.
3. Current Great Library main at
   `12f4cc249b2b5dc268d05d1698fe9c5e3079327d` as read-only program context.
4. The official Project Gutenberg feed/rights pages, Library of Congress
   Classification outline, JSON Schema Draft 2020-12, Python gzip/tar behavior,
   and SQLite semantics listed in `docs/source-register.md`.
5. Tiny tracked fixtures designed to make stale rows, queue overlaps, Unicode,
   same-name contributors, institutional labels, role variation, payload offsets,
   and digest behavior observable offline.

## Decision 1 — rebuild a complete source snapshot, then atomically replace

**Observed risk.** In-place upserts can update rows that still exist but cannot
prove removal of rows, shelves, subjects, classes, contributor edges, or locators
that disappeared upstream.

**Decision.** Both metadata and contributor builders construct a sibling temporary
SQLite database, validate it, close it, and atomically replace the destination.
A locator re-index deletes the complete route set for one container inside the
same transaction before inserting current members.

**Rejected alternative.** Incremental `INSERT OR REPLACE` into a long-lived
production database. It leaves stale dependent rows unless every deletion path is
perfectly mirrored.

**Proof.** `test_source_replacement_and_timestamp_independent_logical_digest`,
`test_roles_unicode_aliases_and_source_replacement_without_name_merge`, and
`test_deterministic_pack_offsets_checksums_and_locator_replacement`.

## Decision 2 — claim logical reproducibility, not unsupported SQLite byte identity

**Observed risk.** Build timestamps and SQLite page layout are not canonical data.
A byte-for-byte database promise would be stronger than the evidence.

**Decision.** A reproducible build receipt requires the same source SHA-256,
sorted logical digest, and per-table row counts. Retrieval/build timestamps are
recorded but omitted from the logical digest. Binary payload determinism is
reported separately and scoped to the recorded compression toolchain.

**Rejected alternative.** Hash the SQLite file and call any difference a data
change. That conflates storage layout or volatile metadata with logical content.

**Proof.** Two clean fixture builds use different retrieval timestamps and emit
the same logical digest and row counts. The exact values are in
`docs/validation/2026-08-06-fixture-report.json`.

## Decision 3 — preserve useful LoCC letter-plus-digit subclasses

**Observed risk.** The old parser captured only an optional second letter. Codes
such as `D501` and `Q11` were reduced to `D` and `Q`, while comments implied a
more specific subclass.

**Decision.** Normalize whitespace/case, retain the valid top-level LCC class,
and use the next alphanumeric character for the immediate bookcase/subclass:
`D501 -> D5`, `Q11 -> Q1`, `PR838 -> PR`.

**Rejected alternative.** Keep letter-only parsing and update documentation to
match. That would discard useful source-observed specificity.

**Proof.** `test_locc_letter_plus_digit_and_letter_subclasses` plus fixture queue
output containing `D5` and `Q1`.

## Decision 4 — separate queue candidates, reasons, and the one-row Work queue

**Observed risk.** A Work may satisfy several rules and several tiers. A direct
`UNION` queue duplicates Works or discards why they matched.

**Decision.** Publish three views:

- `v_extraction_candidates`: every rule match;
- `v_extraction_reasons`: distinct auditable reasons;
- `v_extraction_queue`: exactly one row per Work at its smallest numeric priority,
  retaining all reasons in deterministic order.

A specific `PZ` rule is not silently promoted by the broad `P` section rule.

**Rejected alternative.** `GROUP BY gid` with an arbitrary reason/tier. That loses
explanations and can choose a lower priority nondeterministically.

**Proof.** `test_extraction_queue_one_row_at_highest_priority_with_all_reasons`
and `test_specific_pz_tier_is_not_promoted_by_broad_language_section`.

## Decision 5 — contributor occurrences are source observations, not people

**Observed risk.** A normalized-name key can merge unrelated humans, an
organisation with a human-looking label, a pseudonym, or repeated appearances of
the same label without authority evidence.

**Decision.** Emit one contributor occurrence per `(Gutenberg Work, source order)`
with a stable source-local observation ID. Unicode is NFC-normalized only for byte
stability. Roles, raw labels, aliases, life-date parsing, and unresolved
human/organisation classification evidence are preserved. A label hash exists
only as `comparison_only_not_identity`.

**Rejected alternatives.** Name-derived `bk:*` person IDs, name-only canonical
merges, or classifying institutions from name shape.

**Proof.** The same literal label on two Works remains two observations; the
fixture retains `平塚, らいてう`, `United Nations [Editor]`, author/editor/translator
roles, and no canonical ID.

## Decision 6 — export the interim observation envelope and remove canonical writes

**Observed risk.** The legacy Book-to-People loader wrote canonical people from
names, flattened roles, and mutated a universal rank/work-count field. The People
Graph v2 schema itself shows identity claims and source-provenance concepts, but
Prompt 7 cannot depend on another branch or silently adjudicate identity.

**Decision.** Keep the old entry-point filename for discoverability, but make it a
read-only NDJSON exporter. Old write flags fail explicitly. Each Work and
contributor occurrence emits `pg-observation-0.1`, source snapshot/time/rights,
payload hash, native IDs, contributions, relationships, evidence, and raw pointer.
The exporter rejects canonical-ID keys and globally unique name/company/location/
biography/topic/handle identifiers.

**Rejected alternative.** Continue writing current v2 tables until v3 lands.
That would preserve the unsafe behavior this lane was asked to eliminate.

**Proof.** `test_pg_observation_export_has_no_canonical_identity` and
`test_envelope_validator_rejects_canonical_and_name_identifier`.

## Decision 7 — make the documented random-access payload format fully tracked

**Observed risk.** Documentation described individually gzipped members inside an
uncompressed tar with exact offsets, but the complete pack/index/verify procedure
was not reproducible from tracked tooling.

**Decision.** Add deterministic fixture packing, payload and locator manifests,
per-member compressed/uncompressed SHA-256, exact tar content offsets/lengths,
source replacement for locator routes, and full verification. Gzip timestamps and
tar metadata are normalized; the tar remains uncompressed for byte-range access.

**Rejected alternatives.** Compress the outer tar (destroying direct random byte
ranges), hide the packing step, or trust a locator without member checksums.

**Proof.** Two fixture packs have the same tar SHA-256. The verifier checks every
member and reports zero errors. A legacy locator fails with an explicit
regeneration instruction rather than receiving a partial unverifiable migration.

## Decision 8 — rights are explicit and publication remains gated

**Observed risk.** Public visibility or a metadata row is not a universal text
reuse grant. Project Gutenberg rights are item- and jurisdiction-sensitive.

**Decision.** Every source/build/payload receipt carries a closed rights state,
terms revision, rights basis, observation/retrieval time, and source digest.
`pending` is valid and blocks publication. The fixture texts are synthetic and
explicitly marked as such. No production payload is downloaded, committed, or
uploaded by this lane.

**Rejected alternative.** Treat every Gutenberg row or text as globally public
domain without a recorded basis.

## Decision 9 — version contracts and leave the modern-book model additive

**Decision.** Track JSON Schemas for source, observation, payload, locator, and
release receipts. Document a future Work/Expression/Edition/Item model and modern
metadata bridges without turning this PR into a new ingest or assigning canonical
identities.

**Reason.** Prompt 7 requires a parallel-compatible seam. An additive observation
contract is independently testable; a speculative global ontology would conflict
with other lanes.

## Decision 10 — public receipts exclude runtime paths

**Observed risk.** An exact-CI rerun in a different temporary directory produced
the same metadata, contributor, observation, payload, and tar digests but a
different aggregate release hash. Raw component-manifest file hashes included
local `database`, `output`, and `tar` paths, so build topology leaked into release
identity.

**Decision.** Written component receipts recursively remove runtime-only artifact
and source-input paths. Release v3 computes `component_receipt_sha256` over a
canonical public projection, not the raw input JSON file. Payload manifest v3
also omits source-relative input paths. Runtime return values still expose local
locations to the invoking process, but they are not publication metadata.

**Rejected alternatives.** Normalize only the tracked fixture path, or retain a
raw manifest-file hash beside the logical hash. Both leave equivalent releases
path- or formatting-sensitive and can expose private directory structure.

**Proof.** `test_release_receipt_is_independent_of_local_paths_and_formatting`
builds equivalent component receipts under two different checkout paths and JSON
formats and requires identical release objects. Two complete fixture pipelines
under distinct work directories now produce release manifest SHA-256
`11e482cd8fbc5bf0991db81b6ac4e285a19a2137c5719395357fbc4fb27c88cd`.

## Reproduction sequence

```bash
python3 -m compileall -q scripts tests
python3 -m unittest discover -s tests -v
python3 scripts/run_fixture_pipeline.py \
  --work-dir /tmp/siso-book-library-fixture --clean
```

Compare the emitted report with
`docs/validation/2026-08-06-fixture-report.json`. Production assets must be
regenerated and separately rights-reviewed; the fixture result is not a claim
about current release payload bytes.
