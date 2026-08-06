# Engineering decision journal

This is the reproducible rationale behind the implementation: evidence inspected,
alternatives considered, decisions taken, and the seams left for later lanes.
It is intended to let another agent reconstruct the work from the repository.

## 2026-08-06 — Establish the evidence boundary

**Observed:** the source catalog supplies Work rows and contributor strings, not
canonical People Graph entities. It also supplies a Project Gutenberg release
date, not the original print publication date.

**Decision:** preserve source-native Work identity (`Text#`) and source-listed
attribution occurrences. Do not manufacture a person ID from a label. Mark the
release-date semantics explicitly in every Work observation.

**Rejected:** keep the normalized-name key but call it provisional. A key used as
a database primary key still performs a merge, regardless of its label.

## 2026-08-06 — Choose full replacement for snapshot projections

**Observed:** every metadata table and edge in this repository is derivable from
one complete catalog snapshot. Incremental diff logic would need explicit delete
handling for every current and future table.

**Decision:** build a new database beside the target, run integrity and foreign-
key checks, then atomically replace the target. This makes absence in the source
mean absence in the projection and gives rollback-on-failure for free.

**Rejected:** `INSERT OR REPLACE` plus per-table cleanup. It duplicates source
reconciliation rules and is easy to forget when adding a new edge table.

**Future seam:** a truly incremental upstream feed may later use append-oriented
source observations. Its compaction/projection step should still produce an
exact snapshot with the same logical digest contract.

## 2026-08-06 — Define reproducibility honestly

**Observed:** SQLite binary bytes can vary with SQLite/runtime/page-layout details,
while rows and schema remain equivalent. Gzip and tar bytes can be deterministic
when timestamps, user/group metadata, order, paths, and compression parameters
are normalized.

**Decision:**

- SQLite: authoritative `logical_sha256` over ordered table names, columns, and
  canonicalized rows; report `binary_sha256` only as a receipt.
- NDJSON: canonical JSON key order and one LF-terminated record per line;
  SHA-256 is authoritative.
- Payload: deterministic gzip members (`mtime=0`, no stored filename) in
  deterministic uncompressed USTAR containers; asset SHA-256 is authoritative.

**Rejected:** claim byte-identical SQLite without measuring it across supported
platforms. The release manifest explicitly records that this claim is false.

## 2026-08-06 — Resolve LoCC parsing

**Observed:** main classes and subclasses are alphabetic; the following digits
are the class number. The old comment and parser disagreed for `D501`.

**Decision:** store normalized full code, one-letter section, full alphabetic
subclass, and numeric stem. Preserve `bookcase` as the compatibility column name
for subclass. Tier rules use section for broad classes, subclass for precise
classes such as `PA`, `PN`, and `PZ`.

**Rejected:** define “bookcase” as the first two characters, which would turn
`D501` into `D5` and mix numeric classification with alphabetic subclass.

## 2026-08-06 — Model the queue as a projection

**Observed:** a Work can legitimately satisfy many rules and several tiers.
Discarding overlap hides why a Work was selected; returning every match breaks
queue cardinality.

**Decision:** retain all rule candidates, choose minimum `tier_rank`, aggregate
winning reasons into a stable list, and separately aggregate all reasons. Store
no tier on the canonical Work row.

## 2026-08-06 — Keep contributor occurrences unresolved

**Observed:** a label can denote a human, organisation, pseudonym, or ambiguous
catalog attribution. Source life dates support a person *candidate* but are not
an identity bridge. Parenthetical forms and pseudonym markers are evidence, not
aliases to auto-merge globally.

**Decision:** one contributor observation per `(Work, source order)`. Preserve
role, literal role, raw label, display label, aliases, pseudonym markers, life
values, unresolved kind state, source snapshot, and evidence hash. Export the
occurrence as an unresolved `claim` subject because the shared envelope has no
`contribution_occurrence` subject kind.

**Rejected:** assign `person` or `organisation` solely from punctuation or words
in the name. A future source can provide explicit kind evidence.

## 2026-08-06 — Retire direct canonical mutation

**Observed:** the old loader opened a canonical graph and matched by normalized
name. There is no safe compatibility mode for that behavior.

**Decision:** keep the command name so old automation gets an explicit error,
but make `--apply` fail closed before the graph path is opened. Without `--apply`,
the command exports observations.

## 2026-08-06 — Reconcile payload documentation and implementation

**Observed:** random access to an uncompressed tar can use exact member offsets;
individually compressed members retain per-book transfer savings. A compressed
outer tar would destroy efficient random access.

**Decision:** pack one deterministic `.txt.gz` member per Work inside uncompressed
USTAR. The payload manifest records content and compressed-member hashes, sizes,
asset, member path, offset, and length. The locator independently rescans the tar
and verifies those bytes before release receipt generation.

**Rejected:** trust the pack manifest without rereading the asset. That would let
a corrupted or substituted tar pass through unchanged.

## 2026-08-06 — Rights and public-safety boundary

**Observed:** source metadata and payload rights are different questions, and
jurisdiction matters. A source string such as “Public domain in the USA” must not
be generalized to worldwide public domain.

**Decision:** source manifests carry metadata rights/basis. Every Work retains the
literal payload-rights field and a narrow normalized state such as
`not_restricted_us` or `pending`. Release receipts aggregate those states but do
not upload payloads or assert broader rights.

## 2026-08-06 — Validation strategy

The acceptance tests deliberately use two complete snapshots, not only repeated
identical input:

- v1 contains four catalog rows, six contributor occurrences, a legacy field,
  one non-text item, overlapping tiers, Unicode, a pseudonym marker, and three
  payload members.
- v2 removes two rows, adds one Work, changes roles/metadata/subjects/classes,
  removes a column, changes one payload, removes one payload, and adds another.

This proves both same-input idempotency and changed-source replacement. The test
suite runs without network access and treats unclosed-resource warnings as
errors.
