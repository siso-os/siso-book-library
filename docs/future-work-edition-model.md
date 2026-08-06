# Future Work, Expression, Edition, and modern-book bridge

This change does not perform a modern-book ingest. It records the model and
source seams needed to add one without embedding a title string directly on a
person edge.

## Proposed layers

- **Work**: the abstract intellectual creation.
- **Expression**: a language, translation, revision, or adaptation of a Work.
- **Edition**: a publisher/date/format realization of an Expression.
- **Item or payload**: one retrievable file, scan, or text with its own checksum
  and rights state.
- **Contribution**: a typed, ordered, and optionally time-bounded relation from a
  source-observed contributor to any of those layers.

A Gutenberg ebook ID is a strong source-native identifier for the Gutenberg
record/payload route, not automatically a global Work identifier. Titles and
contributor names remain attributes. Translation, editing, illustration, and
compilation roles must not be flattened into authorship.

## Modern metadata bridge

A bounded future pilot can add metadata-only observations from:

- Open Library Work/Edition identifiers and author authority links;
- DOI/Crossref records for books, chapters, and contributor roles;
- ISBNs with explicit edition scope and known reuse limitations;
- ORCID, VIAF, ISNI, Library of Congress, Wikidata, or equivalent authority IDs
  when the source literally provides the link.

The pilot should emit the same observation envelope, preserve source conflicts,
and keep rights/update/removal rules with each source snapshot. A title/name pair
may generate a review candidate but never an accepted identity or Work merge.

## Promotion gates

Scale a modern source only when it demonstrates measurable gains in edition
resolution, contributor-role coverage, stable-ID bridges, or decision value.
Kill or constrain it when identifiers are ambiguous, bulk reuse is unclear,
updates/deletions cannot be reproduced, or it mainly adds duplicate titles.
Full text remains a separate rights-gated plane; metadata visibility is not text
reuse permission.
