# C7 fixtures

`Append` payloads (`record_json`) for the validator and tests.

| File | Expected | Exercises |
|------|----------|-----------|
| `valid-tier0.json` | valid | tier-0 auto-allow, no snapshot |
| `valid-tier2-snapshot.json` | valid | tier-2 user-allow with `snapshot_ref` and `deployment_before` |
| `invalid-has-hash.json` | invalid | client tried to supply writer-assigned `ts`/`prev_hash`/`hash` |
| `invalid-float.json` | invalid | float inside `input_redacted` (C1 forbids floats) |
