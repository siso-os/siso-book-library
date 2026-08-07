# Future Work / Expression / Edition bridge

This PR intentionally keeps current Gutenberg `Text#` records source-native. It
does not attempt a full bibliographic ontology or network ingest. The following
model is the next compatibility seam.

## Proposed entities

### Abstract Work

The intellectual creation independent of language or edition. It must have a
stable internal ID only after evidence-backed reconciliation; a title string is
not an identifier.

### Expression

A realization of the Work, such as a language, translation, adaptation, or
revision. Translator and editor roles attach here when the source evidence is
expression-specific.

### Edition / Manifestation

A publisher/date/format/ISBN-specific publication. Original print publication
dates belong here, not in the Project Gutenberg release-date field.

### Digital Item

A source-hosted file or eBook realization. Gutenberg `Text#`, formats, source
URLs, payload checksum, and release date attach here. A single Gutenberg item may
have been derived from more than one print edition, so the Edition link can be
unknown or contested.

## Bridge strategy

1. **Retain Gutenberg observations unchanged.** They remain evidence even after
   later reconciliation.
2. **Open Library:** use source-native author keys and Work/Edition keys as
   candidate locators. Preserve alternate names and every source relationship;
   do not accept an author match from search ranking or name equality alone.
3. **Crossref:** use DOI as a Work/edition identifier where applicable and retain
   deposited contributor roles, ORCID/ROR identifiers, dates, license data, and
   update state as source observations.
4. **Authority identifiers:** VIAF, ISNI, Library of Congress authority IDs,
   Wikidata QIDs, and ORCID may supply strong bridges when the literal source
   relationship is available. Their scope, authority, and conflict state must be
   declared.
5. **Crosswalks are claims.** A Gutenberg item ↔ Open Library edition or DOI link
   carries method, evidence, confidence, status, observed time, and reviewer;
   rejected/undone links do not delete source records.

## Candidate matching order

Strongest first:

1. explicit source-to-source identifier link
2. exact authority identifier agreement with no conflict
3. ISBN/DOI/edition evidence plus compatible contributor and language evidence
4. title/contributor/date similarity as a review candidate only

Title or contributor-name equality alone never auto-accepts.

## Kill gates for a future pilot

Stop or revise the bridge if:

- manually reviewed precision for accepted links is below the agreed threshold;
- conflicting stable identifiers are overwritten rather than preserved;
- original print dates are inferred from Gutenberg release dates;
- rights/update/deletion metadata cannot be retained;
- the process needs full copyrighted payloads when metadata/evidence locators
  would answer the research question.
