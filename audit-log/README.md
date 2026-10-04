# C1 — audit-log contract

Contract C1 defines the Famulus audit log: an append-only NDJSON file in
which famulus-agentd records every agent action, protected by a SHA-256
hash chain. Each record captures who did what (actor, tool, redacted
input), under which permission decision and tier, with which snapshot and
deployment context, and with what result.

Consumers:

- **famulus-auditd** (root system service) is the sole writer: famulus-agentd
  submits one record per agent action over the C7 `org.famulus.Audit1`
  interface (`dbus-audit/`), and the service assigns `ts`, `prev_hash`,
  and `hash` per HASHING.md, keeping one chain per uid.
- **famulus-gui** and external auditors verify and display it, using
  `validate_chain.py` or any conforming reimplementation.

## Files

- `audit-record.schema.json` — JSON Schema (draft 2020-12) for one audit
  record.
- `HASHING.md` — normative (RFC 2119) specification of canonical JSON,
  the hash chain, the NDJSON file format, and a worked test vector.
- `validate_chain.py` — reference chain verifier CLI; also exports the
  reference `canonical_json()` and `record_hash()` functions.
- `fixtures/valid-chain.ndjson` — 4-record chain that verifies.
- `fixtures/tampered-payload.ndjson` — payload altered after hashing
  (hash mismatch).
- `fixtures/broken-link.ndjson` — prev_hash linkage broken between
  records 1 and 2.
- `fixtures/bad-genesis.ndjson` — first record's prev_hash is not all
  zeros.
- `fixtures/README.md` — what each fixture exercises.
- `test_audit_log.py` — unittest suite for the schema, verifier, and
  test vector.

## Running the verifier

From the repository root:

```
.venv/bin/python audit-log/validate_chain.py audit-log/fixtures/valid-chain.ndjson
```

Optionally pass `--schema PATH` to use a schema other than the
`audit-record.schema.json` next to the script. Exit codes: 0 verified,
1 validation failure, 2 usage error.

## Running the tests

From the repository root:

```
.venv/bin/python -m unittest discover -s audit-log -v
```

## Stability

Frozen at tag contracts-v1. Changes require an ADR, maintainer review, and a new frozen tag; already-frozen tags are never rewritten.
