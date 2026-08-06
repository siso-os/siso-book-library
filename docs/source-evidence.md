# External source evidence ledger

Checked: 2026-08-06  
Policy: primary/official documentation only. Observed facts are separated from
implementation inferences. URLs are recorded so a later agent can reverify terms
and API behavior before a production ingest.

## Project Gutenberg — offline catalogs and machine-readable metadata

Official URL: <https://www.gutenberg.org/ebooks/offline_catalogs.html>

Observed facts:

- Project Gutenberg directs database/tool builders to its machine-readable
  metadata rather than crawling the website.
- XML/RDF metadata is updated daily; the CSV catalog is updated weekly.
- the metadata tracks Project Gutenberg's eBook release date and does not include
  original print-source publication dates;
- an all-text zipped tar is listed as a weekly artifact, but this PR does not
  download or redistribute it.

Implementation impact:

- source acquisition is manifest-driven and snapshot/digest-pinned;
- `book.issued` and exported `issued` are explicitly labeled as Gutenberg release
  dates, not print publication dates;
- tests use synthetic fixtures only; production download remains a separate,
  rights-reviewed operation.

Terms/rights locator: <https://www.gutenberg.org/policy/license>

Observed boundary: Project Gutenberg and jurisdictional copyright status require
careful wording. The implementation retains the literal per-Work rights string
and uses the narrow state `not_restricted_us` rather than asserting worldwide
public domain.

## Library of Congress — Classification Outline

Official URL: <https://www.loc.gov/catdir/cpso/lcco/lccowp.html>

Observed fact: the official outline lists alphabetic main classes (for example,
D for general/European history and P for language/literature) and links each main
class to its subclasses.

Implementation inference: an LCC value is parsed into alphabetic main class and
subclass plus a following numeric stem. Thus `D501` is class/subclass `D` with
number `501`, while `PR6019` is main class `P`, subclass `PR`, number `6019`.
The inference is encoded in tests and kept separate from any claim to implement
the complete subscription classification schedules.

## Open Library — Authors API

Official URL: <https://openlibrary.org/dev/docs/api/authors>

Observed facts:

- author search returns source-native author keys such as `OL…A` and alternate
  names;
- an individual author can be fetched by its key as JSON;
- Works can be listed from the author-key endpoint with pagination/limits.

Implementation impact: the future bridge uses Open Library keys as source-native
identifiers and treats search/name similarity only as candidate evidence. No
network adapter or accepted identity link is added in this PR.

## Crossref — REST API

Official URL: <https://www.crossref.org/documentation/retrieve-metadata/rest-api/>

Observed facts:

- the public REST API returns deposited scholarly metadata in JSON;
- available metadata can include funding, licenses, updates, abstracts, ORCID,
  and ROR identifiers;
- Crossref exposes Work and DOI endpoints and documents rights caveats for some
  fields such as abstracts.

Implementation impact: the future bridge proposes DOI/ORCID/ROR observations and
source-specific rights handling. It does not ingest or persist Crossref data in
this PR.

## Repository evidence

Baseline repository commit:
`be9ab0831b9ea8802d6898f3a3dfa8a61c63e80b`

Files inspected:

- `README.md`
- `scripts/build_books_module.py`
- `scripts/build_people_graph.py`
- `scripts/load_into_people_graph.py`
- `scripts/build_locator.py`
- `scripts/probe_text_layer.py`
- `index/tier_queries.sql`

Read-only compatibility context inspected:

- People Graph v2 schema and its explicit identity/provenance comments at commit
  `de048bb3b34bf931b56fd741cb46c1334acdfb98`.

No external code was copied. The implementation uses Python standard-library
modules and repository-local contracts.
