# Architecture audit entry point

The 2026-08-06 first-principles audit is preserved in three artifacts:

- [`docs/first-principles-audit-2026-08-06.md`](docs/first-principles-audit-2026-08-06.md) — complete source-domain re-derivation, findings, alternatives, uncertainty, target model, and execution order.
- [`docs/release-contract-v2.md`](docs/release-contract-v2.md) — proposed immutable index, payload, locator, export, rights, validation, and Great Library release contract.
- [`tools/verify_audit_findings.py`](tools/verify_audit_findings.py) — executable source and SQLite fixture checks for direct graph writes, locator digest mismatch, wall-clock reproducibility, section/bookcase filtering, queue deduplication, source actor keys, packaging visibility, and automated-test coverage.

Run:

```bash
python3 tools/verify_audit_findings.py
```

The verifier records when a historical finding no longer reproduces after a repair. Do not delete the reasoning that motivated a correction; update its status and attach the fixing commit and validation receipt.
