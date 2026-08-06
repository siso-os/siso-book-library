# Book index integrity and reproducibility

## Source replacement, not incremental residue

`scripts/build_books_module.py` builds into a sibling temporary SQLite file and
atomically replaces the destination only after schema checks, foreign-key checks,
queue creation, row counts, and a logical digest succeed. A new source snapshot
therefore replaces the prior snapshot as a whole. A removed Work cannot leave
behind stale `book_field`, subject, shelf, LoCC, or subject-facet rows.

`scripts/build_people_graph.py` applies the same rule to contributor observations.
It never mutates an existing contributor database in place, so removed Works and
roles cannot leave stale contributor edges.

The source receipt records:

- source ID and source-native snapshot ID;
- source URI class and exact SHA-256;
- observed and retrieved timestamps;
- terms revision and closed-vocabulary rights state;
- rights basis and acquisition method;
- loader and schema versions;
- per-table row counts and a stable logical digest.

## Logical reproducibility

SQLite file bytes can vary because page layout and volatile build timestamps are
not the logical dataset. The supported equality test is:

1. identical source SHA-256;
2. identical row counts;
3. identical logical digest over sorted, non-volatile rows.

The fixture runner deliberately uses different retrieval timestamps for two clean
builds of the same snapshot and requires their logical digests and row counts to
match. It does not claim byte-for-byte SQLite identity.

Written component manifests recursively omit runtime-only `database`, `output`,
`tar`, and source-input path fields. Aggregate release manifests hash a canonical
public component projection rather than raw JSON bytes. Therefore checkout paths,
temporary directories, and whitespace formatting cannot change release identity
or leak local build topology.

```bash
python3 scripts/run_fixture_pipeline.py
```

To retain the generated fixture receipts outside the repository:

```bash
python3 scripts/run_fixture_pipeline.py \
  --work-dir /tmp/siso-book-library-fixture --clean
```

## LoCC parsing

The parser keeps the top-level section and a useful immediate subclass. It now
handles both letter and digit subclasses:

| Source code | Section | Bookcase/subclass |
| --- | --- | --- |
| `PR838` | `P` | `PR` |
| `D501` | `D` | `D5` |
| `Q11` | `Q` | `Q1` |

Tier views use the top-level section where a tier is defined by section, while
specific subclasses such as `PA`, `PN`, and `PZ` remain available for targeted
rules. Comments, stored values, and tests now agree.

## Extraction queue contract

`index/tier_queries.sql` exposes three layers:

- `v_extraction_candidates`: every rule match, including overlaps;
- `v_extraction_reasons`: distinct auditable reason rows;
- `v_extraction_queue`: exactly one row per Gutenberg Work.

The queue selects the smallest numeric priority (`tier1` before `tier2` before
`tier3`) and retains every matched reason in deterministic priority/name order.
A biography classified under a broad hold section remains one `tier1` row with
both reasons. A `PZ` romance with no higher-value rule remains `tier3` rather than
being promoted by the broad language section.

## Migration from current release indexes

Existing released SQLite indexes predate the source/build manifest tables and
must be regenerated from a pinned catalog snapshot before they can make the new
reproducibility claim. The new builders do not rewrite a production asset in
place. They create replacement artifacts and receipts that can be compared before
publication.
