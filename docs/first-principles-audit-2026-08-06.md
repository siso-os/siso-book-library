# SISO Book Library — first-principles audit and contract re-derivation

**Research date:** 2026-08-06  
**Repository:** `sisodias/siso-book-library`  
**Related systems:** `sisodias/siso-people-graph`, `sisodias/great-library-of-siso`  
**Status:** source-linked audit; current observations, reproduced behavior, architectural inference, proposals, and unknowns are kept distinct

---

## 1. Executive conclusion

The SISO Book Library is valuable because it turns a large public-domain source universe into a queryable, rights-aware, artifact-addressable data product. Its strongest principles should be retained:

- preserve upstream metadata rather than hand-curating substitutes;
- model subjects and classifications as relations;
- keep contribution roles distinct;
- keep artifact identity separate from location;
- support BCE dates;
- avoid treating a folder hierarchy as ontology;
- test text quality before extraction;
- distribute large payloads outside Git history.

The first-principles correction is that the repository currently combines or implies several contracts that need to be made explicit:

1. a **source snapshot** contract for the exact Gutenberg catalog observed;
2. a **source record** contract preserving catalog assertions;
3. a **Work / expression / artifact** contract that does not equate a Gutenberg item with every abstract Work concept;
4. a **versioned export** contract for the People Graph;
5. a **payload package and locator** contract whose checked-in implementation matches its README claims;
6. an **immutable dataset release** contract with builder receipts and checksums;
7. a **versioned research profile** contract replacing universal-sounding extraction tiers;
8. a **deterministic-content** contract distinguishing reproducible data from observation metadata.

The Book Library should remain a source-domain owner. It should not decide canonical cross-domain human identity and should not write directly into one particular People Graph database schema.

---

## 2. Reasoning record policy

This document preserves the premises, repository evidence, bounded reproductions, alternatives, implications, proposed contracts, kill gates, and uncertainty needed for another agent to reconstruct the conclusion.

The companion executable verifier is [`../tools/verify_audit_findings.py`](../tools/verify_audit_findings.py). The proposed immutable release contract is [`release-contract-v2.md`](release-contract-v2.md).

A token-by-token private scratchpad is not treated as a source of truth. The auditable chain is:

```text
pinned source → observation → bounded reproduction → inference → proposal → validation gate
```

---

## 3. Source scope inspected

The audit inspected source introduced by or visible after these commits:

- `c2f12b1476a2889d125e409e1652c0eb99c75f56` — initial Book Library index, builders, locator, integration, and README;
- `3a5d1875b395342730205100e99443308d3263e3` — extraction queue views and measured queue results;
- `be9ab0831b9ea8802d6898f3a3dfa8a61c63e80b` — published payload documentation.

Files:

- `README.md`
- `scripts/build_books_module.py`
- `scripts/build_people_graph.py`
- `scripts/load_into_people_graph.py`
- `scripts/build_locator.py`
- `scripts/probe_text_layer.py`
- `index/tier_queries.sql`
- `.gitignore`

Cross-system evidence included:

- People Graph schema, query, and loader files at commit `de048bb3b34bf931b56fd741cb46c1334acdfb98`;
- Great Library `docs/registry-model.md`;
- Great Library `docs/question-driven-research.html`;
- Great Library `schemas/release.schema.json`;
- Great Library `registry/source-inventories/gutenberg-corpus-2026-08-03.json`;
- Great Library GQ-009 evidence addressability update at commit `12f4cc249b2b5dc268d05d1698fe9c5e3079327d`.

The GitHub connector did not expose arbitrary execution against the published SQLite release assets. Row counts and remote payload claims are therefore treated as repository assertions unless a source commit documents a measured receipt. The verifier uses synthetic SQLite fixtures for SQL semantics and source inspection for contract mismatches.

---

## 4. First principles for a source-domain library

### 4.1 Preserve what the source said

The Book Library should be able to answer:

- which upstream snapshot was observed;
- which exact source row produced a normalized record;
- what was parsed versus copied verbatim;
- which parser and policy version were used;
- what changed between snapshots;
- which rights statement applies;
- where each artifact can be retrieved;
- how an independent agent can verify the release.

The existing `raw` row and `book_field` table point in the right direction.

### 4.2 Source identity is not canonical intellectual identity

A Gutenberg `Text#` is a stable source-local item identity. It may represent:

- one edition;
- one translation;
- one collected volume;
- an abridgement;
- a compilation;
- a source transcription;
- a non-text media record.

It should not automatically be treated as the same thing as an abstract intellectual Work.

### 4.3 Source author strings are not canonical humans

A catalog author string is an upstream attribution record. It may contain:

- a human;
- an institution;
- a collective label;
- `Various` or `Anonymous`;
- a role suffix;
- an uncertain or incomplete date;
- a transliterated or inverted name;
- several contributors in one field.

The Book Library should parse and preserve these source actors, but canonical cross-domain actor resolution belongs to the People Graph.

### 4.4 Roles attach to contributions and levels

The current decision to preserve author, editor, translator, illustrator, commentator, compiler, and related roles is correct.

A stronger model recognizes that roles can attach to different levels:

- author → abstract Work;
- translator → language expression;
- editor → edition;
- scanner/OCR contributor → artifact;
- uploader or packager → distribution artifact.

Where the source lacks enough information, the system should retain a source-level attribution rather than fabricate a precise level.

### 4.5 Classification is evidence, not universal value

LCSH and Library of Congress classifications are highly valuable source metadata. They support browse and retrieval. They do not create one universal ranking of importance.

An extraction queue is a purpose-specific research profile. It should carry:

- profile ID and version;
- decision purpose;
- query logic;
- source snapshot;
- membership reasons;
- exclusions;
- expected downstream action;
- validation counts.

### 4.6 Artifact identity is separate from location

A work or artifact can be retrieved through several routes:

- upstream plaintext;
- human-readable upstream page;
- local archive byte range;
- release asset byte range;
- future mirror or object store.

Locations can change. The artifact identity and digest should not.

### 4.7 Reproducibility requires pinned inputs and policy

“Rebuildable” can mean several different things:

1. **semantically rebuildable:** same normalized facts from equivalent source input;
2. **content reproducible:** same logical tables after excluding volatile metadata;
3. **byte reproducible:** identical SQLite bytes;
4. **independently verifiable:** a clean agent can confirm source, builder, policy, and output checksums.

The repository should state which guarantee applies. Writing the wall clock into every row prevents identical content bytes unless the clock is pinned or separated.

### 4.8 Release assets need immutable evidentiary identities

A corrected operational asset may need replacement, but an evidence system cannot preserve reproducibility if the same release version silently serves different bytes later.

The safe rule is:

> New bytes create a successor release with a new manifest and digest. Old evidentiary bytes remain addressable or are explicitly recorded as unavailable, never silently redefined.

---

## 5. Findings

### BL-P0-001 — Direct People Graph integration bypasses safe canonical resolution

`scripts/load_into_people_graph.py` opens a canonical graph database for writing, creates a lowercased whitespace-normalized map of existing names, and reuses an existing person ID on equality.

This has several problems:

- it makes the Book Library depend on a specific graph schema;
- it lets a source-domain loader decide canonical cross-domain identity;
- name equality bypasses the People Graph’s identity-claim discipline;
- it creates a second integration path alongside `siso-people-graph/loaders/build_people_graph_v2.py`;
- the two paths target different schema generations and role semantics;
- correction and provenance behavior can diverge.

**Decision:** the Book Library should publish a versioned normalized export. The People Graph should consume that export and own canonical actor assignments.

**Deprecation gate:** do not delete the old script until a migration fixture proves equivalent source coverage and a successor interface exists. Mark it as legacy and unsafe for new canonical builds.

### BL-P0-002 — The README’s per-book SHA-256 locator claim is not represented by the checked-in locator schema

The payload documentation states that `locator.sqlite` maps every GID to:

```text
(asset, offset, length, sha256)
```

The checked-in `scripts/build_locator.py` schema stores:

- GID;
- container;
- member;
- offset;
- length;
- encoding;
- route;
- URI;
- indexed time.

It does not store a SHA-256 digest. The inspected builder scans tar headers and records positions; it does not read or hash each member payload.

This does not prove that the published locator lacks hashes — the remote binary was not inspected — but it proves the checked-in builder cannot reproduce the documented schema as written.

**Decision:** either update the README to the actual reproducible contract or check in the packaging and hashing implementation that produces the claimed release. The preferred path is the latter.

### BL-P0-003 — The deterministic rebuild claim conflicts with wall-clock content

`build_books_module.py` assigns the current UTC wall clock to `fetched_at` and writes it into every book row. The people builder likewise creates output based on a current build execution.

If the same source CSV is processed twice at different times, the logical observation metadata changes. The SQLite bytes will also generally differ.

The Great Library source inventory describes the index as reproducible byte-for-byte. That is too strong unless:

- `observed_at` is passed explicitly and pinned;
- volatile build metadata is separated from content tables;
- SQLite creation details are normalized;
- output digests are measured on clean rebuilds.

**Decision:** define reproducibility precisely and implement a release build manifest. A sensible default is content reproducibility plus independent verification, with byte reproducibility treated as an additional measured property rather than assumed.

### BL-P1-004 — A Gutenberg item is not always an abstract Work

The current `book` table uses GID as the primary book identity. This is correct as a source-local record, but cross-domain research needs a distinction among:

```text
source item
abstract Work
expression or translation
edition or artifact
retrieval locator
```

Without it, “everything Plato produced” can return modern translations, editions, or collected forms as if Plato directly produced every source artifact.

**Decision:** keep GID as the source item ID and add an export contract capable of linking source items to higher-level Work identities when evidence supports it. Do not force unsupported FRBR-like precision into every row.

### BL-P1-005 — Source classifications are correctly relational but actor topic rollups need derivation boundaries

The Book Library correctly stores subjects, shelves, and classes as edge tables. The People Graph currently rolls LCSH subjects directly into `person_topic` for every contribution role.

This can misstate source evidence:

- a translator may be linked to the work’s subject without being its original thinker;
- an editor may work on a topic without endorsing it;
- a subject heading classifies the source item, not the contributor’s belief.

**Decision:** export source classifications at the work/source-item level. Let the People Graph derive actor output profiles with role, source vocabulary, and method visible.

### BL-P1-006 — Section-level extraction logic uses `bookcase` in a way that excludes many intended subclasses

`build_books_module.py` parses a class such as `QA` into:

```text
section = Q
bookcase = QA
```

`v_tier1_core` compares `bookcase` to values including `Q`, `R`, and `T`. A `QA` book therefore does not match `bookcase = 'Q'`, even though the policy comment says the Science section is core.

The same issue affects other section-level lists and `v_tier2`.

**Decision:** section-level policy should filter the `section` column. Bookcase-level policy should name exact bookcases. Do not mix the two semantic levels.

### BL-P1-007 — The extraction queue described as deduplicated can contain one GID several times

`v_extraction_queue` combines views using `UNION`, but each row includes a different `reason`. SQL `UNION` deduplicates complete rows, not the GID alone.

A book qualifying as both biography and core section remains two distinct rows because the reason differs. The commit itself reports more queue rows than distinct books, confirming the behavior.

**Decision:** represent profile membership reasons separately or aggregate them. The queue should have one row per source item with a deterministic priority and a list or relation of all reasons.

### BL-P1-008 — “Tier” implies universal value when the logic is a purpose-specific research profile

The current views encode a useful owner-selected extraction priority. The word “tier” can be misread as an intrinsic property of a book or field.

The repository’s own finding that thousands of high-priority books sit inside the broad Literature section shows why fixed universal hierarchy is fragile.

**Decision:** rename the concept to `extraction_profile` or `research_profile`. Version it and attach its decision purpose. Preserve raw classifications so future profiles can disagree without rewriting the source index.

### BL-P1-009 — The author parser is useful but its identity key is source deduplication, not canonical identity

`build_people_graph.py` constructs a normalized `person_key` from name and available life years. This is appropriate for source-local grouping, but:

- missing years leave same-name collision risk;
- Unicode normalization removes non-ASCII characters under the current regular expression;
- institutional detection based on commas and years is heuristic;
- a shared name with dates can still contain catalog errors;
- `Anonymous`, `Various`, pseudonyms, and collectives require richer actor types.

**Decision:** call the result a source actor key and export all raw variants and parser evidence. Canonical resolution belongs downstream.

### BL-P1-010 — Payload and locator provenance need one checked-in build path

The README documents six release assets, individual gzip members in uncompressed tar containers, HTTP Range retrieval, a locator, and per-book checksums.

The inspected repository contains a generic tar header locator but not the complete checked-in pipeline that:

1. acquires and pins upstream payload;
2. normalizes or selects each text artifact;
3. compresses each member individually;
4. packs the uncompressed tar shards under size limits;
5. computes member digests;
6. writes remote and local routes;
7. validates byte ranges;
8. emits a manifest;
9. publishes assets;
10. performs a clean remote retrieval check.

**Decision:** check in the release packager and validator or narrow the README claim to what the repository can reproduce.

### BL-P1-011 — Rights need artifact- and jurisdiction-aware inheritance

The current `public_domain_us` label is appropriately narrower than a blanket public-domain claim. The next contract should preserve:

- source assertion;
- jurisdiction;
- artifact or edition scope;
- observation date;
- upstream licence notice;
- redistribution decision;
- quotation/extraction boundary;
- unknown or pending states.

A source Work may be public domain while a modern translation, introduction, cover, scan, OCR correction, or compilation carries different rights.

### BL-P1-012 — Text quality is correctly gated but needs a versioned artifact-quality observation

`probe_text_layer.py` is a strong example of measured ingest quality. It samples across the body and distinguishes text, partial text, and OCR-required files.

The quality result should become a typed observation tied to:

- artifact digest;
- probe version;
- sample pages;
- thresholds;
- tool versions;
- observation date;
- OCR sidecar identity where used.

This prevents a quality verdict from drifting when an artifact or method changes.

### BL-P1-013 — Automated contracts are missing from the initial public source

The inspected initial commit contains builders, SQL, documentation, and ignore rules but no checked-in test suite or CI workflow.

Before changing parsers, packaging, or exports, add:

- source-row round-trip fixtures;
- author parser fixtures including Unicode and adversarial cases;
- BCE and uncertain-date fixtures;
- section/bookcase profile tests;
- one-row-per-GID queue tests;
- deterministic release-manifest tests;
- locator and range retrieval fixtures;
- rights inheritance fixtures;
- People Graph export contract fixtures.

---

## 6. Re-derived Book Library model

### 6.1 Source snapshot

```text
source_snapshot
  source_snapshot_id
  source_name
  source_locator
  observed_at
  source_revision_or_last_modified
  source_digest
  acquisition_method
  rights_notice
```

Every normalized row and artifact points to a source snapshot.

### 6.2 Source item

```text
source_item
  source_item_id          Gutenberg GID
  source_snapshot_id
  media_type
  raw_row
  normalized_title
  language
  upstream_issued_date    explicitly Gutenberg release/digitization date
```

Do not overload `issued` as original publication date.

### 6.3 Source actor and attribution

```text
source_actor
  source_actor_id
  source_snapshot_id
  display_name
  raw_variants
  actor_kind_guess
  birth_assertion
  death_assertion
  parser_version

source_attribution
  source_actor_id
  source_item_id
  role
  raw_evidence
```

The actor kind is a source-local classification or hypothesis, not canonical cross-domain truth.

### 6.4 Classification

```text
source_classification
  source_item_id
  scheme
  value
  hierarchy_depth
  source_snapshot_id
```

Keep LCSH, LoCC, Gutenberg shelves, and future vocabularies distinct.

### 6.5 Work and artifact linkage

```text
work_candidate_link
  source_item_id
  external_or_canonical_work_id
  relation               edition_of | translation_of | contains | adapts | unknown
  status
  method
  evidence
```

Do not auto-collapse source items into abstract Works without evidence.

### 6.6 Artifact and locator

```text
artifact
  artifact_id
  source_item_id
  media_type
  encoding
  content_digest
  byte_length
  rights_state

artifact_location
  artifact_id
  route
  immutable_uri_or_container
  offset
  length
  observed_at
  availability_state
  retrieval_receipt
```

A route can change without changing the artifact digest.

### 6.7 Research profile

```text
research_profile
  profile_id
  version
  decision_purpose
  source_snapshot_id
  query_revision
  created_at

profile_membership
  profile_id
  source_item_id
  priority
  reason
```

One source item can have several reasons while the materialized queue returns one deterministic item row.

---

## 7. Versioned People Graph export

The Book Library should export source-domain facts rather than mutate a graph database directly.

Suggested release contents:

```text
manifest.json
source_snapshots.ndjson
source_items.parquet
source_actors.parquet
source_attributions.parquet
source_classifications.parquet
artifacts.parquet
artifact_locations.parquet
work_candidate_links.parquet
validation.json
checksums.sha256
```

The export guarantees:

- stable source-local IDs;
- lossless source references;
- role preservation;
- date precision and raw evidence;
- rights state;
- artifact addressability;
- no canonical cross-domain actor merge;
- pinned schema and builder versions.

The People Graph then imports source actors and makes resolution assignments under its own policy.

---

## 8. Proposed release workflow

A release should be reproducible from a public manifest:

```text
1. acquire pinned catalog snapshot
2. verify source digest and metadata
3. build normalized source tables
4. run round-trip and parser fixtures
5. acquire or select payload artifacts
6. compute artifact digests
7. package immutable shards
8. build locator against final shard bytes
9. validate local byte ranges
10. validate remote byte ranges after publication
11. generate validation report and checksums
12. publish immutable release assets
13. register exact Work/Release evidence in the Great Library
```

See [`release-contract-v2.md`](release-contract-v2.md) for the proposed manifest and acceptance gates.

---

## 9. Reproduction notes

Run:

```bash
python3 tools/verify_audit_findings.py
```

The verifier checks:

- source integration uses normalized-name direct matching;
- the README claims locator SHA-256 while the checked-in schema lacks a digest column;
- the builder writes wall-clock `fetched_at` values;
- a synthetic `QA` book is omitted by the current section-intended `bookcase` filter;
- a synthetic book with several reasons remains several queue rows;
- the people key normalization is source-local and ASCII-lossy;
- no test or workflow directories are present in the original structure.

The verifier is designed to make findings disappear after repairs. It is not a permanent gate requiring bugs to remain.

---

## 10. Alternatives considered

### Keep direct People Graph writes because they are simple

**Rejected.** Simplicity at the source boundary creates coupling, duplicate integration logic, and unsafe canonical identity decisions.

### Treat every GID as the canonical abstract Work

**Rejected.** It cannot represent translations, editions, collections, adaptations, and artifact-specific roles truthfully.

### Implement a full library-science ontology immediately

**Rejected.** The minimum model should be driven by tested queries. Unsupported precision is another form of false certainty.

### Keep tier labels as a global value system

**Rejected.** The profile is purpose-specific and the existing evidence already shows high-value material crossing broad sections.

### Store corpus payload in Git history

**Rejected.** The existing release-asset direction is sound. The correction is immutable manifests and checked-in packaging, not moving large bytes into Git history.

### Promise byte-for-byte determinism without measuring it

**Rejected.** Define and test content reproducibility, independent verification, and byte reproducibility separately.

### Use the People Graph’s canonical IDs inside source rows

**Rejected.** Source-local identity must survive changes in the downstream canonicalization policy.

---

## 11. Immediate execution order

### Phase 0 — Baseline contracts

1. add tests and CI;
2. reproduce section/bookcase and queue duplication behavior;
3. record the current public release assets, sizes, and checksums;
4. retrieve a sample book from every documented route;
5. compare actual locator schema with README claims.

### Phase 1 — Stop unsafe coupling

1. mark `load_into_people_graph.py` as legacy;
2. define a versioned source export;
3. create source actor and attribution fixtures;
4. ensure no name match becomes a canonical merge in this repository.

### Phase 2 — Correct semantic contracts

1. source snapshot identity;
2. source item versus Work candidate;
3. artifact and locator with digest;
4. date precision and raw evidence;
5. role target levels;
6. research profiles replacing universal tiers.

### Phase 3 — Reproducible release pipeline

1. check in payload packaging;
2. pin source and build clock;
3. generate manifest, validation, and checksums;
4. test local and remote ranges;
5. publish immutable successor releases;
6. register exact releases in the Great Library.

### Phase 4 — Expansion

Only then add other book and document sources, using the same source snapshot, rights, actor, attribution, artifact, and export contracts.

---

## 12. Confidence and unknowns

### High-confidence findings

- direct normalized-name graph matching exists;
- the locator builder schema lacks a SHA-256 field;
- the README claims per-book SHA-256 in the locator;
- the builder writes wall-clock values;
- section-intended policy filters `bookcase` using one-letter values;
- queue rows can remain duplicated by differing reason;
- source actor normalization is not a safe canonical identity method;
- the initial public implementation lacks checked-in automated tests.

### Unverified in this audit

- the exact schema and checksums of the currently published release binaries;
- whether remote release assets have ever been replaced;
- whether a separate unpublished packaging script exists elsewhere;
- full-corpus parser error rates;
- actual byte-for-byte rebuild behavior on a pinned environment;
- rights status of every individual modern translation or artifact;
- performance and storage cost of the proposed exports.

These remain explicit unknowns. Future agents must not infer them from README prose.

---

## 13. Final decision

The Book Library should become a reproducible, rights-aware, source-faithful data product that exports stable facts and retrievable artifacts to the rest of the SISO research system.

Its canonical flow is:

```text
pinned Gutenberg snapshot
  → lossless source records
  → source actors and role-bearing attributions
  → source classifications
  → Work/version/artifact candidates
  → digested artifact locations
  → versioned normalized export
  → People Graph canonical resolution
  → question-driven evidence selection
  → Great Library release and answer lineage
```

The success measure is not how many files are stored. It is whether a cold agent can identify, retrieve, verify, interpret, and correctly attribute the exact source artifact needed for a consequential question.
