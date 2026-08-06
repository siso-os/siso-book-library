# Task specification: Book Library integrity and parallel graph export

Date received: 2026-08-06  
Repository: `sisodias/siso-book-library`  
Branch: `books/integrity-export-parallel-20260806`

This file preserves the implementation lane that produced this change so later
agents can evaluate scope without relying on chat history.

## Exclusive ownership

This lane may change:

- `scripts/**`
- `index/**`
- new `tests/**`, `manifests/**`, and `docs/**`
- `.github/workflows/**`

Generated SQLite databases, tar archives, gzip members, or corpus payloads must
not be committed.

## Mission

Make the Book Library metadata index, contributor graph, locator, extraction
queue, and People Graph export honest, reproducible, source-replaceable, and
versioned.

## Required outcomes

1. Prove source replacement and rerun idempotency. Removed source rows must also
   remove stale Works, fields, subjects, shelves, classifications, contributor
   edges, locators, and payload assets.
2. Replace unsupported byte-identical SQLite claims with measured logical
   digests, source hashes, row counts, and separate binary receipts.
3. Correct and test Library of Congress Classification parsing, including
   letter-plus-digit values.
4. Produce one extraction-queue row per Work at its highest priority while
   retaining an auditable list of every matching reason.
5. Track the complete payload pipeline: deterministic per-book gzip members in
   uncompressed tar assets, exact byte ranges, lengths, and per-book SHA-256;
   index and verify those receipts without hidden local steps.
6. Replace name-based canonical merging with `pg-observation-0.1` source
   observations. The export must never assign a canonical People Graph ID.
7. Preserve contributor roles, order, aliases, institutional labels,
   pseudonym markers, Unicode, and unresolved entity-kind state.
8. Record source digest, source/retrieval times, terms and rights basis, row
   counts, loader/schema versions, and a public-safe release manifest.
9. Add tiny offline fixtures and CI.
10. Document a future Work/Expression/Edition model and a modern-book bridge via
    source-native Open Library, Crossref, and authority identifiers without
    turning this lane into a network ingest.

## Acceptance criteria

- Two clean fixture builds have equal logical receipts.
- Stale-edge, queue-deduplication, locator-checksum, role-preservation, and
  observation-envelope tests pass offline.
- No generated database or corpus asset is committed or uploaded.
- Add `docs/handoff-parallel-people-graph.md`.
- Push the branch and open a draft PR titled
  `Books: make the index and People Graph export reproducible`.
