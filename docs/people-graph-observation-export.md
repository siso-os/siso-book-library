# Book Library to People Graph observation export

## Why the export changed

The former loader matched a Book Library contributor to a canonical person by a
normalized name, created `bk:<name-derived-key>` IDs, retained only authorship,
and wrote Work count into a universal rank field. None of those operations is
safe evidence of identity.

`scripts/load_into_people_graph.py` is now a compatibility entry point for a
read-only export. Passing the old `--graph` or `--apply` options fails explicitly.
The implementation source of truth is
`scripts/export_people_graph_observations.py`.

## No name-only merge

Every contributor row is one source occurrence identified by:

```text
gutenberg:work:<gid>:contributor:<order>
```

Two Works that both say `Doe, Jane [Author]` produce two contributor observations.
They share a SHA-256 label key only as a comparison aid. That key is marked
`comparison_only_not_identity`, is never emitted as a unique identifier, and
never creates a canonical cluster.

The source does not reliably classify human versus organisation. Contributor
occurrences therefore use subject kind `claim` with
`entity_kind_state=unresolved` and candidate kinds `person` and `organisation`.
`United Nations [Editor]`, `Anonymous`, pseudonyms, and personal-looking
institution names are preserved without a name-shape verdict.

## `pg-observation-0.1` mapping

Each Work record includes:

- source snapshot/native Work ID, timestamps, terms, rights, and raw-row digest;
- source-native Gutenberg ID with explicit source scope, stability, and
  uniqueness semantics;
- title, language, Gutenberg issue date, media type, source URL, rights state,
  LCSH subjects, bookshelves, and LoCC classifications;
- every contributor role and source order;
- a pointer to the replayable source row.

Each contributor occurrence includes:

- source snapshot and Work/order-native observation ID;
- literal source label, parsed display string, dates, aliases/pseudonyms, and
  unresolved entity-kind evidence;
- role, order, contribution relationship, and literal-field evidence;
- no identifiers and no canonical People Graph ID.

The exporter validates the closed rights vocabulary, payload hash, required
fields, identifier semantics, and prohibition on canonical ID keys. Names, handles, companies, employers, locations, biographies, and topics are
rejected when promoted to globally unique identifiers; source-scoped mutable
identifiers may still be represented with honest semantics.

## Unicode and role preservation

Labels are normalized only to Unicode NFC for stable byte comparison. Characters
are not transliterated or deleted. Role suffixes such as author, editor,
translator, illustrator, commentator, and compiler remain distinct contribution
edges. Parenthetical names are retained as source-observed aliases rather than
silently replacing the label.

## Downstream seam

A People Graph ingestion lane may import the NDJSON as observations, then propose
identity candidates from stronger evidence such as authority IDs. It must not
reinterpret the comparison-only label key as a person ID. Accepted identity
review belongs downstream; the Book Library remains a source-observation producer.
