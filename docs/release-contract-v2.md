# SISO Book Library release contract V2 — proposal

**Status:** proposed; not yet an accepted release schema  
**Date:** 2026-08-06  
**Purpose:** make every published index and payload version independently identifiable, verifiable, rebuildable from pinned inputs, and safely consumable by the People Graph and Great Library

---

## 1. Contract objective

A cold agent holding a Book Library release identifier must be able to answer:

1. Which exact Gutenberg catalog snapshot was used?
2. Which exact source and builder commits created the release?
3. Which schema and parser policy versions were applied?
4. Which artifacts were published?
5. What is the SHA-256 digest and size of every artifact?
6. What rights state applies to metadata and payload artifacts?
7. How can one source item be retrieved without downloading the whole corpus?
8. Which validations passed or failed?
9. What changed from the predecessor?
10. Which known coverage gaps or unsupported claims remain?

A release is immutable. New bytes require a new release identity.

---

## 2. Required release bundle

```text
manifest.json
catalog.sqlite.gz
source-actors.sqlite.gz
locator.sqlite.gz
normalized-export.tar
validation.json
checksums.sha256
```

Payload releases may be separate from index releases but must use the same immutable manifest principles:

```text
payload-manifest.json
payload-000.tar
payload-001.tar
...
payload-locator.sqlite.gz
payload-validation.json
checksums.sha256
```

The normalized export should use open, streamable formats where practical:

```text
source_snapshots.ndjson
source_items.parquet
source_actors.parquet
source_attributions.parquet
source_classifications.parquet
artifacts.parquet
artifact_locations.parquet
work_candidate_links.parquet
```

SQLite remains the portable query snapshot. Parquet or NDJSON provides a source-neutral interchange plane.

---

## 3. Proposed manifest

```json
{
  "schema_version": "2.0.0",
  "release_id": "siso-book-library:index-v2.0.0",
  "release_kind": "index",
  "released_at": "2026-08-06T00:00:00Z",
  "immutable": true,
  "predecessor_release_id": "siso-book-library:index-v1",
  "source_repository": {
    "repository": "sisodias/siso-book-library",
    "commit": "<git-sha>"
  },
  "builder": {
    "entrypoint": "scripts/build_release.py",
    "commit": "<git-sha>",
    "python": "3.x.y",
    "sqlite": "3.x.y",
    "policy_versions": {
      "catalog_parser": "2.0.0",
      "source_actor_parser": "2.0.0",
      "rights_policy": "1.0.0",
      "research_profile": "none"
    }
  },
  "source_snapshots": [
    {
      "source_snapshot_id": "project-gutenberg-catalog-2026-08-02",
      "source": "Project Gutenberg bulk catalog",
      "locator": "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv",
      "observed_at": "2026-08-03T00:00:00Z",
      "last_modified": "2026-08-02T00:00:00Z",
      "sha256": "<digest>",
      "bytes": 0,
      "rights_state": "public_metadata"
    }
  ],
  "artifacts": [
    {
      "artifact_id": "catalog-sqlite",
      "filename": "catalog.sqlite.gz",
      "media_type": "application/gzip",
      "uncompressed_media_type": "application/vnd.sqlite3",
      "bytes": 0,
      "sha256": "<digest>",
      "availability": "public",
      "rights_state": "public_metadata",
      "content_semantics": "normalized and lossless Gutenberg catalog snapshot"
    }
  ],
  "row_counts": {
    "source_items": 0,
    "source_actors": 0,
    "source_attributions": 0,
    "source_classifications": 0,
    "artifacts": 0,
    "artifact_locations": 0
  },
  "validation": {
    "report_artifact_id": "validation-json",
    "status": "passed",
    "checks": {
      "source_digest": "passed",
      "lossless_round_trip": "passed",
      "parser_fixtures": "passed",
      "foreign_keys": "passed",
      "row_count_invariants": "passed",
      "artifact_digests": "passed",
      "local_range_retrieval": "passed",
      "remote_range_retrieval": "passed",
      "people_graph_export_contract": "passed"
    }
  },
  "coverage": {
    "source_universe": "Project Gutenberg catalog snapshot <id>",
    "media_types_retained": ["Text", "Sound", "Dataset", "Image"],
    "payload_scope": "declared separately",
    "known_gaps": []
  },
  "rights": {
    "metadata": "public_metadata",
    "payload_default": "public_domain_us",
    "jurisdiction_note": "Non-US status must be evaluated separately.",
    "exceptions": []
  },
  "reproducibility": {
    "guarantee": "content_reproducible_and_independently_verifiable",
    "build_clock": "pinned_from_manifest",
    "byte_reproducible": "measured|not_measured|failed",
    "clean_build_receipts": []
  },
  "known_limitations": []
}
```

---

## 4. Source snapshot rules

Every upstream input must carry:

- source name;
- stable snapshot ID;
- immutable digest;
- byte size;
- observed time;
- source last-modified or revision when available;
- acquisition method;
- source locator;
- rights notice;
- retrieval receipt.

A mutable URL is a locator, not a version. The digest and observation metadata establish the snapshot.

If the upstream file changes between acquisition and build, the build must fail rather than silently consuming a mixed snapshot.

---

## 5. Build clock and deterministic metadata

The release build must not call the wall clock independently for every row.

Use one explicit manifest value:

```text
BUILD_OBSERVED_AT=2026-08-03T00:00:00Z
```

All normalized records that need build observation metadata receive this pinned value or reference the source snapshot record.

Prefer separating volatile execution receipts from semantic content:

```text
semantic tables          source facts and normalized records
release manifest         pinned observation and build identity
validation report        execution environment and timings
```

### Reproducibility levels

The manifest must select one or more measured guarantees:

- `semantic_reproducible` — equivalent normalized facts;
- `content_reproducible` — canonical table exports have identical digests;
- `byte_reproducible` — compressed release artifacts have identical bytes;
- `independently_verifiable` — source, builder, and outputs can be checked by a clean agent.

Do not claim byte reproducibility unless two clean builds in pinned environments produce identical artifact digests.

---

## 6. Artifact and locator rules

Every artifact must have:

- stable artifact ID;
- source item or Work candidate relation;
- media type and encoding;
- byte length;
- SHA-256 digest;
- rights state;
- generation or acquisition method;
- source snapshot;
- one or more locations.

Every location must have:

- route type;
- immutable or version-bound URI/container;
- offset and length where applicable;
- observation time;
- availability state;
- retrieval validation receipt.

### Range-addressable container rule

For an artifact inside a tar shard:

```text
range_start = member_content_offset
range_end   = member_content_offset + member_length - 1
```

Validation must:

1. retrieve that exact range;
2. compare byte length;
3. compare SHA-256;
4. decompress if the member is individually compressed;
5. validate the decoded artifact identity;
6. record HTTP status and response headers for remote checks.

The locator schema and README must describe the same fields.

---

## 7. Payload packaging rules

The packager must be checked into the repository and versioned.

It must:

1. accept a pinned source snapshot or artifact set;
2. choose deterministic shard boundaries or record the exact policy;
3. individually compress members when random access requires it;
4. keep the outer container seekable;
5. enforce release-host asset limits;
6. compute member and shard digests;
7. build the locator from final shard bytes;
8. emit a manifest before publication;
9. validate local retrieval;
10. publish without replacing an existing immutable release;
11. validate remote retrieval;
12. update the validation report with remote receipts.

Do not manually create release assets outside the recorded builder and then describe the result as reproducible.

---

## 8. Normalized export contract

The export is the only supported integration surface for the People Graph.

### Required source entities

```text
source_snapshot
source_item
source_actor
source_attribution
source_classification
artifact
artifact_location
work_candidate_link
```

### Required guarantees

- source-local IDs remain stable within the pinned snapshot policy;
- raw variants and source evidence are retained;
- roles are not flattened;
- corporate, collective, pseudonymous, anonymous, and unknown actors are not silently discarded;
- dates preserve precision and uncertainty;
- rights and locators are included;
- no cross-domain canonical actor ID is assigned;
- schema version and checksums are in the release manifest.

### Prohibited behavior

- opening a People Graph SQLite file for writes;
- merging a source actor into an existing canonical actor by normalized name;
- importing a downstream ranking or canonical identity back into the source truth tables;
- dropping source rows because they are not currently useful to a People Graph query.

---

## 9. Research profile rules

Extraction priorities must be published as separate versioned profiles, not stored as intrinsic book tiers.

A profile carries:

```json
{
  "profile_id": "siso-book-library:research-profile:foundational-knowledge-v1",
  "version": "1.0.0",
  "decision_purpose": "prioritize source items for question-driven extraction",
  "source_release_id": "siso-book-library:index-v2.0.0",
  "query_revision": "<git-sha>",
  "membership_count": 0,
  "distinct_source_item_count": 0,
  "reasons": [],
  "known_biases": [],
  "validation": {}
}
```

The materialized membership relation contains one row per `(profile, source_item, reason)`. A queue projection may choose one priority row per item while preserving all reasons.

Section-level selection uses the section field. Bookcase-level selection uses exact bookcase values.

---

## 10. Rights rules

Rights attach at the appropriate level:

- source catalog metadata;
- abstract Work where known;
- translation/expression;
- edition;
- scan or OCR artifact;
- packaged distribution artifact.

Minimum fields:

```text
rights_state
jurisdiction
source_assertion
observed_at
scope
redistribution_state
quotation_or_extraction_boundary
evidence
```

Valid uncertainty states include `pending` and `unknown`. Unknown rights block payload redistribution but do not require discarding public metadata.

A public-domain original does not automatically make a modern translation, introduction, cover, scan, or OCR correction public domain.

---

## 11. Validation report

`validation.json` must include:

- release ID;
- source and builder commits;
- environment versions;
- start and end times;
- source digest checks;
- source-row round-trip results;
- parser fixture counts and failures;
- BCE and date-precision fixtures;
- source actor role fixtures;
- foreign-key checks;
- row-count invariants;
- duplicate and orphan checks;
- export schema validation;
- local artifact retrieval samples;
- remote artifact retrieval samples;
- checksum validation;
- rights exception counts;
- known failures and waived checks;
- final status.

A validation failure cannot be converted to “passed” by omitting the check. Waivers must be explicit, scoped, and evidenced.

---

## 12. Great Library integration

The Great Library should register:

1. **SISO Book Library** as an independently addressable Work;
2. each source-code or data-product version as an immutable Release;
3. exact artifact locators, revisions, availability, rights, and digests;
4. distribution states established by validation receipts;
5. a selected release only through a new Snapshot.

The Gutenberg corpus Source Inventory remains useful as source-intake evidence. It is not a substitute for the Book Library Work and exact data-product Release.

Catalog presence must not imply downloadable, verified, portable, or redistributable status unless the Release manifest supplies the evidence.

---

## 13. Success criteria

V2 is ready when a clean agent can:

1. download the manifest;
2. verify source and artifact checksums;
3. reconstruct or independently validate the normalized index;
4. inspect all source actor and role evidence;
5. retrieve a sampled source item through every declared route;
6. prove that returned bytes match the artifact digest;
7. consume the normalized export without writing source-specific SQL;
8. reproduce profile membership counts;
9. identify rights and known coverage gaps;
10. cite the exact Release in the Great Library.

---

## 14. Kill gates

Do not publish V2 when any of these is true:

- the manifest points to mutable inputs without digests;
- the checked-in builder cannot recreate the documented schema;
- the locator lacks artifact digests while the README claims them;
- remote byte-range validation has not been run for a published payload route;
- source actors are silently merged into canonical humans;
- an extraction profile is stored as intrinsic book value;
- release assets are replaced under an existing immutable version;
- rights state is inferred beyond available evidence;
- validation failures are hidden or removed from the report.
