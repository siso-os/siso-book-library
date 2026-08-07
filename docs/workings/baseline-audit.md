# Baseline audit: Book Library main at `be9ab083`

Audit date: 2026-08-06  
Baseline commit: `be9ab0831b9ea8802d6898f3a3dfa8a61c63e80b`  
Method: static inspection of every tracked builder/query file, followed by tiny
fixtures that encode the failure conditions. No production database or payload
was required.

## Findings

### BL-001 — Existing builds are additive, not source-replaceable

**Severity:** high  
**Baseline paths:** `scripts/build_books_module.py`,
`scripts/build_people_graph.py`, `scripts/build_locator.py`

The metadata builder opens the destination in place, creates tables if absent,
and inserts/replaces current rows. It does not remove Works or edge rows that
vanish from a later source snapshot. The contributor and locator builders have
the same persistence problem: rows for a removed Work or archive member can
survive indefinitely.

**Violated invariant:** the current database must be an exact projection of one
declared source snapshot.

**Resolution:** build metadata and contributor databases into fresh sibling
files, validate them, then atomically replace the destination. Reindexing a
locator container first deletes that container's previous rows; the full release
command also prunes containers absent from the replacement payload manifest.
Fixture v1→v2 proves removed Work `1002`, media item `1005`, its old field,
edges, and stale payload assets disappear.

### BL-002 — LoCC code, comment, and classification semantics disagree

**Severity:** high  
**Baseline path:** `scripts/build_books_module.py`

The baseline comment says `D501` maps to `D5`, while its regular expression only
captures alphabetic characters and therefore returns `D`. More importantly,
Library of Congress Classification syntax separates an alphabetic class/subclass
from the following number: `D501` is main class/subclass `D`, numeric stem `501`;
`PR6019` is main class `P`, subclass `PR`, numeric stem `6019`.

**Violated invariant:** code, comments, stored columns, and priority queries must
use the same classification semantics.

**Resolution:** parse and store `section`, alphabetic `subclass` (retaining the
legacy column name `bookcase` for compatibility), and `numeric_stem`. Broad
priority rules use `section`; precise rules use `bookcase`/subclass. Tests cover
`D501`, `PR6019`, and `QA76.73`.

### BL-003 — The extraction queue is not one row per Work

**Severity:** high  
**Baseline path:** `index/tier_queries.sql`

The baseline queue unions rows containing both Work and reason. A Work matching
several rules remains several distinct rows because the reason differs. It also
lets a lower-tier row coexist with a higher-tier row.

**Violated invariant:** queue cardinality is one row per Work at the highest
priority, while overlap remains inspectable.

**Resolution:** materialize rule candidates, select the minimum tier rank per
Work, and aggregate ordered `reason_list` and `all_reason_list` values. The
builder asserts `COUNT(*) = COUNT(DISTINCT gid)` after installing the views.

### BL-004 — Published payload claims lack a tracked producer/verifier chain

**Severity:** high  
**Baseline paths:** `README.md`, `scripts/build_locator.py`

The published layout describes individually gzipped members inside uncompressed
tar assets and per-book hashes, but the tracked locator scans a different raw
text-tar shape and stores no member or content checksum. There was no tracked
pack or verify command able to reproduce the documented offsets and hashes.

**Violated invariant:** every locator row must be reproducible from a tracked
asset manifest and independently verifiable from its exact byte range.

**Resolution:** `pack_payload.py` produces deterministic gzip members in
uncompressed USTAR assets; `build_locator.py` indexes compressed member ranges
and both compressed/content hashes; `verify_payload.py` seeks to every range,
checks the member hash, decompresses it, and checks content length/hash.

### BL-005 — Contributor identity is silently canonicalized by name

**Severity:** critical  
**Baseline paths:** `scripts/build_people_graph.py`,
`scripts/load_into_people_graph.py`

The baseline contributor builder derives a key from a normalized label and life
years, strips non-ASCII characters from the key, and merges all matching rows.
The direct People Graph loader then matches existing canonical rows by normalized
name. This can conflate unrelated humans, institutions, pseudonyms, and aliases,
and it loses the distinction between source evidence and an identity decision.

**Violated invariant:** names are observations, never global unique identifiers;
Book Library export cannot assign canonical identity.

**Resolution:** the contributor database now stores one source occurrence per
Work and source order. It preserves raw/display labels, aliases, role, order,
Unicode, life-date evidence, pseudonym markers, and unresolved kind state. The
only output to People Graph is validated `pg-observation-0.1` NDJSON. The legacy
loader fails closed on `--apply` and never opens the target graph.

### BL-006 — “Deterministic” conflates logical and binary reproducibility

**Severity:** medium  
**Baseline paths:** `README.md`, metadata and contributor builders

The baseline builders write wall-clock timestamps and make no measured
cross-platform SQLite equivalence claim. Even with stable logical rows, SQLite
page layout and runtime versions can change binary bytes.

**Violated invariant:** a release must state what equivalence was actually
measured.

**Resolution:** source manifests supply fixed observed/retrieved timestamps;
logical digests canonicalize table definitions and sorted rows. Binary SHA-256
is retained as a build receipt but is not the authority. Payload bytes are
separately deterministic because gzip/tar metadata are normalized.

### BL-007 — Non-author contribution roles are dropped at the canonical boundary

**Severity:** high  
**Baseline path:** `scripts/load_into_people_graph.py`

The baseline direct loader filters to `author`, so editor, translator,
illustrator, compiler, and other source-listed contributions do not cross the
boundary despite being preserved upstream.

**Violated invariant:** contribution role and order are evidence and must survive
export.

**Resolution:** every source-listed role and order is emitted on the Work record
and on a separate unresolved attribution-claim record. No role is promoted to a
person-wide property.

## Why the chosen fixes are additive

- Existing `book` columns used by read-only callers remain present.
- Existing `person` and `person_work` names remain as compatibility views, but
  their rows explicitly represent source occurrences rather than resolved people.
- The old direct loader path remains callable for migration safety but refuses
  mutation and points callers to the observation export.
- New contracts are versioned, and all generated assets remain outside Git.
