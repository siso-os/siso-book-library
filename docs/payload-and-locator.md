# Payload packing, indexing, and verification

## Physical format

Each Work is compressed independently as deterministic gzip and stored in an
uncompressed USTAR container:

```text
fixture-001.tar
  books/1001.txt.gz
  books/1002.txt.gz
  books/1003.txt.gz
```

The outer tar remains uncompressed so a client can request exactly
`offset..offset+length-1`. Gzip metadata and tar metadata are normalized:

- gzip `mtime = 0`
- no gzip source filename
- tar `mtime = 0`
- tar uid/gid = 0
- stable member order by Gutenberg ID
- stable `books/{gid}.txt.gz` member names

## Pack

```bash
python3 scripts/pack_payload.py \
  --input-manifest manifests/fixtures/payload-v1.json \
  --out-dir /tmp/book-payload \
  --asset-prefix fixture \
  --max-members 10
```

The generated payload manifest records, for every member:

- source-native Work ID and source URI
- narrow rights state
- uncompressed content bytes and SHA-256
- compressed member bytes and SHA-256
- asset name and asset SHA-256
- member path
- exact content offset and compressed length in the tar

## Index

```bash
python3 scripts/build_locator.py \
  --tar /tmp/book-payload/fixture-001.tar \
  --db /tmp/locator.sqlite \
  --container fixture-001.tar \
  --stored-path payload/fixture-001.tar \
  --uri release://payload/fixture-001.tar \
  --indexed-at 2026-08-06T00:10:00Z \
  --route release
```

Reindexing the same container replaces its complete member set, so a deleted
member cannot linger. Machine-local `stored_path` is excluded from the locator's
logical equivalence digest; public URI/range/hash data is included.

## Verify

```bash
python3 scripts/verify_payload.py \
  --locator /tmp/locator.sqlite \
  --asset-root /tmp
```

For every locator row, verification opens the declared tar, seeks to the exact
range, checks the compressed member hash, decompresses it, and checks
uncompressed length and content hash. A release manifest is not emitted if any
member fails.

## Security and safety

- Member paths are generated, never accepted from payload filenames.
- The input manifest digest-checks every source text before packing.
- No extraction to caller-controlled paths is required for verification.
- Generated assets and locator databases are ignored by policy and rejected by
  CI if accidentally tracked.
