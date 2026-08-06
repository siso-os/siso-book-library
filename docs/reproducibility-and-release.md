# Reproducibility and release operations

## One-command fixture build

```bash
PYTHONPATH=scripts python3 scripts/build_release.py \
  --source-manifest manifests/fixtures/catalog-v1.json \
  --payload-input-manifest manifests/fixtures/payload-v1.json \
  --out-dir /tmp/book-library-v1 \
  --built-at 2026-08-06T00:10:00Z \
  --asset-prefix fixture \
  --max-members 10
```

The output directory contains generated `books.sqlite`, `contributors.sqlite`,
`people-graph-observations.ndjson`, `locator.sqlite`, payload tar assets,
`payload-manifest.json`, and `release-manifest.json`. These are release outputs,
not Git inputs.

## Prove two clean builds are equivalent

```bash
first=$(mktemp -d)
second=$(mktemp -d)

PYTHONPATH=scripts python3 scripts/build_release.py \
  --source-manifest manifests/fixtures/catalog-v1.json \
  --payload-input-manifest manifests/fixtures/payload-v1.json \
  --out-dir "$first" --built-at 2026-08-06T00:10:00Z \
  --asset-prefix fixture --max-members 10 > "$first/summary.json"

PYTHONPATH=scripts python3 scripts/build_release.py \
  --source-manifest manifests/fixtures/catalog-v1.json \
  --payload-input-manifest manifests/fixtures/payload-v1.json \
  --out-dir "$second" --built-at 2026-08-06T00:10:00Z \
  --asset-prefix fixture --max-members 10 > "$second/summary.json"

python3 scripts/compare_release_summaries.py \
  "$first/summary.json" "$second/summary.json"
```

## Equivalence policy

| Artifact | Authoritative equivalence | Additional receipt |
|---|---|---|
| Book SQLite | logical SHA-256 over schema/table rows | binary SHA-256 |
| Contributor SQLite | logical SHA-256 over schema/table rows | binary SHA-256 |
| Locator SQLite | logical SHA-256 excluding local path | binary SHA-256 |
| Observation export | canonical NDJSON SHA-256 | record/kind counts |
| Payload | asset and member SHA-256 | byte/member counts |
| Release manifest | canonical pretty JSON file SHA-256 | component receipts |

Binary SQLite equality is intentionally not promised. A release is equivalent
when the logical receipts and deterministic non-SQLite artifacts match.

## Source replacement

Run the same command into an existing output directory with a replacement pair
of source/payload manifests. Metadata and contributor databases are atomically
replaced. The payload packer removes stale assets sharing its prefix. The release
command prunes locator containers not declared by the replacement payload
manifest, then verifies the remaining exact byte ranges.

## Full-data regeneration

A production rebuild requires two locally prepared manifests:

1. A `book-source-1` manifest pointing to a verified Project Gutenberg catalog
   snapshot and its SHA-256.
2. A `book-payload-input-1` manifest listing locally acquired text files, source
   locators, narrow rights states, and content SHA-256 values.

Do not modify the example manifest in place and do not commit absolute local
paths. Build into a governed external data plane, inspect the release manifest,
then publish generated assets through the repository's release process only
after rights and capacity review.
