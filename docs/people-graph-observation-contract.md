# Book Library → People Graph observation contract

## Boundary

The Book Library knows what a particular catalog snapshot says. It does not know
that two labels across Works or platforms denote the same person. Accordingly,
this lane exports observations and attribution claims, never canonical entities.

## Work record

Each source-native Work emits:

- `envelope_version: pg-observation-0.1`
- source/snapshot/native record IDs
- observed/retrieved times, terms revision, metadata rights state, row hash
- subject kind `work`, Gutenberg `Text#`, title, language, media type, and the
  explicit semantics of the Gutenberg release date
- literal payload-rights value plus narrow normalized state
- source-native subjects, shelves, and LCC relationships
- every contribution role and source order
- one source-scoped stable `gutenberg_ebook_id`
- raw source pointer and evidence hash

## Contributor-attribution record

Each `(Work, source order)` occurrence emits a subject kind `claim` with:

- `claim_type: contribution_attribution`
- `identity_state: unresolved`
- raw/display label, aliases, pseudonym markers, literal life values, and
  source-grounded or unresolved entity-kind state
- source-listed role and order
- a source-scoped occurrence identifier that explicitly does **not** identify a
  person
- a relationship back to the source-native Work

The shared envelope has no `contribution_occurrence` subject kind, so `claim` is
the least misleading interoperable representation. A later canonical schema can
map this to a contribution/attribution observation table.

## Validator prohibitions

The validator rejects:

- `canonical_id`, `person_id`, `merged_into`, and equivalent canonical fields at
  any nesting depth
- names, real names, display names, company/employer, location, biography, or
  topic as identifier schemes
- handles/logins declared global, stable, or unique
- missing snapshot, rights, time, hash, evidence, or raw-pointer fields

## Identity handoff

A downstream identity lane may generate candidates using source-native authority
IDs or explicit links. It must keep the source observation unchanged, record
positive and negative evidence, and make any accepted decision reversible. This
export supplies no acceptance signal and should never be treated as one.

## Compatibility command

```bash
python3 scripts/load_into_people_graph.py \
  --books /tmp/books.sqlite \
  --people /tmp/contributors.sqlite \
  --output /tmp/book-observations.ndjson
```

Passing `--apply` exits with status 2 before the graph path is opened. This is an
intentional fail-closed migration from the old name-matching behavior.
