# Reproducible payload packing and locator verification

## Tracked workflow

The repository now contains every step needed to reproduce the documented
random-access layout. No hidden packing step is assumed.

```bash
python3 scripts/pack_payload.py \
  --input-dir /data/gutenberg-texts \
  --tar /build/gutenberg-001.tar \
  --manifest-out /build/gutenberg-001.manifest.json \
  --locator-db /build/locator.sqlite \
  --locator-manifest-out /build/gutenberg-001.locator.json \
  --container gutenberg-001 \
  --snapshot-id <pinned-source-snapshot> \
  --retrieved-at <ISO-8601> \
  --terms-revision <reviewed-revision> \
  --rights-state <open_data-or-pending> \
  --rights-basis <reviewed-basis>

python3 scripts/verify_payload.py \
  --tar /build/gutenberg-001.tar \
  --locator-db /build/locator.sqlite \
  --container gutenberg-001 \
  --payload-manifest /build/gutenberg-001.manifest.json
```

## Physical format

Each source text is compressed independently as `books/<gid>.txt.gz`. The gzip
header is normalized (`mtime=0`, empty filename), and the uncompressed USTAR
container normalizes member order, timestamps, permissions, owner IDs, and owner
names. The tar stays uncompressed, making a member's `offset` and `length` usable
as an HTTP byte range or local seek.

The payload manifest records, per Work:

- Gutenberg ID and tar member name;
- uncompressed byte length and SHA-256;
- compressed member byte length and SHA-256;
- encoding.

Local input paths are deliberately absent from written manifests. They are build
topology, not provenance, and would make otherwise identical receipts differ
between checkouts while potentially exposing private directory names.

The locator records the exact tar content offset, compressed length, encoding,
payload digest, container digest, route, and schema/loader version. Re-indexing a
container deletes every old route for that container before inserting the current
members, so a repack cannot retain stale locator rows.

## Determinism boundary

The same inputs and compression toolchain produce the same fixture tar. The
manifest does not claim that all zlib versions emit byte-identical streams.
Logical equality is the sorted set of Gutenberg IDs plus uncompressed sizes and
hashes; physical equality is the tar SHA-256 under the recorded packer/toolchain.

## Verification

The verifier checks:

- tar SHA-256 and byte size against the container row and payload manifest;
- one-to-one Gutenberg ID coverage between manifest and locator;
- tar metadata offsets and lengths;
- compressed member SHA-256;
- gzip validity;
- uncompressed byte length and SHA-256.

## Existing payload assets

No production payload or SQLite file is created, uploaded, or committed by this
change. Existing payload tar assets may remain usable, but their current locator
index lacks the new per-member digest/schema contract. To publish a conforming
release, regenerate the locator from each existing tar, verify every member, and
publish new manifests/checksums. A legacy locator database fails with an explicit
regeneration message instead of being partially upgraded with unverifiable rows.
