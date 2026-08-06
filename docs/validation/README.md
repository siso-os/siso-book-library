# Validation evidence

These small text/JSON artifacts are committed so reviewers can inspect the exact
offline evidence without downloading generated SQLite or payload files.

Reproduce from a clean checkout:

```bash
python3 -m compileall -q scripts tests
python3 -m unittest discover -v
python3 scripts/run_fixture_pipeline.py --work-dir /tmp/book-library-prompt7 --clean
```

Generated databases, tar files, gzip members, and NDJSON outputs belong in the
chosen work directory and remain outside Git. Compare the command output with the
tracked fixture report. Differences require investigation; the tracked receipt is
not a substitute for rerunning the tests.

The release-receipt regression also runs equivalent inputs under two distinct
checkout paths and JSON formats. Public component and aggregate manifests must
not contain either work directory, and their canonical release hashes must match.
The measured cross-directory result is retained in
`2026-08-06-path-independence.json`.
