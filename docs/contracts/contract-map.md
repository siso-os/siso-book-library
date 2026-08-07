# Contract map

## Data flow

```text
book-source-1 manifest + catalog CSV
        |
        v
book-index-2.0 SQLite ----> extraction views (one Work / best tier)
        |
        +----> contributor-observation-2.0 SQLite
        |                 |
        |                 v
        +----------> pg-observation-0.1 NDJSON

book-payload-input-1 manifest + public-safe text inputs
        |
        v
book-payload-assets-1 manifest + deterministic uncompressed tar assets
        |
        v
book-locator-1.0 SQLite -- exact range/hash verification
        |
        +------------------------------+
                                       v
                              book-library-release-1
```

## Contracts

### `book-source-1`

Declares source/snapshot identity, source URI, observed/retrieved times, terms
revision, metadata rights state/basis, acquisition method, input path/digest,
row contract, and raw-pointer template. The loader verifies the input digest and
required columns before building.

### `book-index-2.0`

An exact projection of one source snapshot. It preserves compatibility columns
from the original index while adding snapshot provenance, literal rights,
normalized narrow rights state, row hashes, foreign keys, corrected LCC fields,
and versioned extraction projections.

### `contributor-observation-2.0`

One row per source attribution occurrence. It is not an identity database. The
primary key is a source occurrence locator, and compatibility `person`/
`person_work` views are explicitly non-canonical.

### `pg-observation-0.1`

The shared parallel-lane envelope. This implementation emits Work observations
and unresolved attribution claims. Validators prohibit canonical fields,
attribute-like identifiers, and globally stable/unique handles.

### `book-payload-input-1`

Declares each payload input by Gutenberg Work ID, file path, source URI, narrow
rights state, and content SHA-256.

### `book-payload-assets-1`

Declares deterministic asset format and every member's content hash, compressed
member hash, sizes, asset, member path, exact offset, and exact length.

### `book-locator-1.0`

Indexes the released asset route. Logical equivalence excludes machine-local
`stored_path` but covers all public route and checksum fields. Verification seeks
and validates every member.

### `book-library-release-1`

Public-safe build receipt covering source identity, component logical/binary
receipts, row counts, payload assets, locator verification, rights coverage, and
explicit negative claims: no canonical identity assignment, no name-only merge,
no production upload, and no asserted byte-identical SQLite reproducibility.

## Compatibility seams

- Existing callers can still read `book`, `book_subject`, `book_shelf`,
  `book_class`, and the old columns on `book`.
- `book_class.bookcase` now consistently means the alphabetic LCC subclass.
- `person` and `person_work` remain views over source occurrences; callers must
  not interpret `person_key` as a canonical person ID.
- `load_into_people_graph.py` remains an entry point but cannot mutate a graph.
- A later People Graph importer can consume NDJSON without importing this
  repository's SQLite schemas.
