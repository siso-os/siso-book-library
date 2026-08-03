# The SISO Book Library

A queryable index over the world's public-domain books. The index is small and
lives in Git; the payload is large and ships as release assets.

**79,071 works · 36,456 people · 184,624 subject edges · 82,405 Library of
Congress classifications · 167,585 topic edges**

## What this is

Not a mirror. The value is the index: who wrote what, when they lived, what it
is about, and where the bytes actually are. Project Gutenberg publishes the
text; this publishes the structure that makes 79,071 books addressable as
*positions held by humans* rather than files in a folder.

Every number above came from catalog metadata alone — no scraping, no model
calls, no hand-curation. Books arrive **pre-classified**: the world's librarians
already assigned Library of Congress Classification and subject headings, so we
inherit a century-old taxonomy instead of inventing one.

## Layout

```
index/     books.sqlite  — works, subjects, LoCC, every upstream column verbatim
           people_books.sqlite — people, roles, life dates
           (shipped as release assets; .gitignored — see "Why releases")
scripts/   the builders. Deterministic: delete the DBs, re-run, get them back.
docs/      design notes
```

## Getting the data

```bash
gh release download index-v1 -R sisodias/siso-book-library
gunzip books.sqlite.gz people_books.sqlite.gz
```

Or rebuild from source in about a minute:

```bash
curl -O https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv
python3 scripts/build_books_module.py --csv pg_catalog.csv --db books.sqlite
python3 scripts/build_people_graph.py --books books.sqlite --db people.sqlite
```

## Getting a book

A reference is an identity, not a location, so every work resolves to routes:

```
gid 84 → https://www.gutenberg.org/ebooks/84.txt.utf-8      (always works)
       → byte range in a release asset: offset 10240, length 448885
```

The direct URL needs no auth and no local copy. The byte-range route exists for
bulk: one HTTP `Range` request pulls a single book out of a multi-gigabyte
archive without downloading or unpacking it. Verified — GitHub release assets
return HTTP 206.

## Why releases, not Git

Git history is permanent. An 182 MB file committed once is 182 MB forever, and
a corrected copy stores both. Release assets can be replaced.

Measured, not assumed — release assets are not counted against repository size:

| Repo | Release assets | Git size |
| --- | --- | --- |
| electron/electron | 1,790 GB | 205 MB |
| ollama/ollama | 925 GB | 88 MB |
| ggml-org/llama.cpp | 252 GB | 414 MB |

(Most recent 100 releases only; true totals are higher.) Limits that are real:
**2 GiB per asset, 1,000 assets per release**, no documented cap on total
release size. This corpus is 11.2 GB — 0.6% of what Electron already stores.

The actual constraint is request volume, not storage. GitHub's acceptable-use
policy forbids "excessive automated bulk activity"; a few thousand fetches a day
is nowhere near it. Cache locally.

## Design decisions worth knowing

**Membership is a relation, not a folder.** Books carry 4.25 subjects each on
average, and 199 of 200 sampled belong to more than one shelf. Filing each under
one directory would discard most of what the catalog knows. Subjects are edge
tables; a shelf is a saved query.

**Roles are distinct edges.** Author, editor, translator, illustrator,
commentator, compiler and more. Flattening them would make a Gutenberg volunteer
editor the second most prolific author in history — that is a real record in
this data, not a hypothetical.

**BCE years are stored negative.** `Plato, 428? BCE-348? BCE` → −428/−348, so
chronological range queries span antiquity instead of silently dropping it.

**Nothing derived is stored.** No score, no tier, no computed rank. Those are
projections over evidence, and storing them is how an index drifts from truth.

**Physical batching is deliberately undecided.** Agents query the index and get
an address; they never navigate directories. So the corpus can be repacked later
without breaking a single reference, and choosing a layout now would optimise for
a usage pattern nobody has observed yet.

## Rights

Project Gutenberg is public domain **in the United States** by construction —
recorded as `public_domain_us`, never a blanket public-domain claim; other
jurisdictions differ. In-copyright works never enter as full text: they enter as
extracted claims with short quotes and rights recorded. Unknown rights block
promotion, and `pending` is a valid and safer answer than a guess.

## Text quality

PDF is a print format, not a text format. `scripts/probe_text_layer.py` samples
12 pages across a document's body — skipping the first 5%, which is exactly
where a scanned book fakes having text — and returns TEXT / PARTIAL /
OCR_REQUIRED.

Measured on a real 342-page scan: `pdftotext` yielded **3,707 words**, because
the body is page images. The same book's Internet Archive OCR sidecar yielded
**131,713 words** — 35× more. Quality is gated at ingest, never assumed.

## Part of

The [SISO Foundry](https://github.com/sisodias) books domain — the fifth
instance of one four-layer loop: scrape the content, scrape the people who made
it, watch them over time, then research over the result.
