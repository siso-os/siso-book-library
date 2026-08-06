# Versioned manifests

The tracked JSON Schemas define the public contracts emitted by the builders.
Generated manifests belong beside generated databases or release artifacts; the
production databases, corpora, tar files, gzip members, and private paths do not
belong in Git.

Written receipts are path-independent: runtime-only database/output/tar/input
locations are removed, and aggregate releases use a canonical component-receipt
hash rather than a hash of formatting- and path-sensitive input JSON bytes.

- `source-manifest.schema.json` describes the metadata-index build receipt.
- `pg-observation-0.1.schema.json` mirrors the interim parallel exchange envelope.
- `payload-manifest.schema.json` describes deterministic member packaging.
- `locator-manifest.schema.json` describes byte-range locator receipts.
- `release-manifest.schema.json` describes a public-safe aggregate receipt.

The Python exporter applies additional invariants that JSON Schema cannot express
concisely: names, companies, locations, biographies, topics, and handles cannot be
promoted to unique identifiers, and no canonical People Graph ID may appear.
