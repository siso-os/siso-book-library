# Changed contracts and migration notes

## Metadata build

Before: open and mutate an existing database in place; wall-clock timestamp;
removed source rows could survive.  
After: verify `book-source-1`, build a complete fresh projection, validate, and
atomically replace. Source/snapshot/times/terms/rights/hash/loader/schema are
queryable.

## LoCC

Before: `bookcase` derivation and comments disagreed for digit-bearing values.  
After: `section` = one-letter main class, `bookcase` = alphabetic subclass,
`numeric_stem` = following number. Broad queue rules use `section`.

## Extraction queue

Before: one row per matching reason/tier.  
After: one row per Work at best tier with `reason_list`, `reason_count`, and
`all_reason_list`.

## Contributor graph

Before: normalized labels/life years became person keys; Unicode was stripped
from identity keys; occurrences merged.  
After: one source occurrence per Work/order, with roles/order/aliases/Unicode/
pseudonym/life/kind evidence intact and no canonical person row.

## People Graph transfer

Before: direct database mutation and normalized-name matching; only author roles
crossed the boundary.  
After: `pg-observation-0.1` NDJSON; every role/order survives; canonical fields and
attribute identifiers are rejected. Direct `--apply` fails closed.

## Payload and locator

Before: locator scanned an undocumented/raw tar shape and stored no hashes.  
After: tracked deterministic pack → manifest → locator → exact range/hash verify
pipeline. Replacements prune stale assets, members, and containers.

## Release receipt

Before: no complete versioned receipt.  
After: `book-library-release-1` includes source identity, row counts, logical and
binary receipts, export validation, payload assets, locator verification, rights
coverage, and explicit limits.

## Assets requiring regeneration after merge

The existing release assets were built under older contracts and are not changed
by this PR. A later governed release run must regenerate and publish, as a
coherent set:

- `books.sqlite` (or compressed release form)
- contributor-observation database replacing any canonicalized Book people
  derivative
- `people-graph-observations.ndjson`
- all payload tar assets and `payload-manifest.json`
- `locator.sqlite`
- `release-manifest.json` and checksums

Do not mix a new locator or release manifest with old payload assets.
