# C7 — org.famulus.Audit1 (dbus-audit)

Contract C7 defines how records reach the C1 audit log. C1 fixes the record
format and hash chain; C7 fixes **who writes it and how**: a root-owned
system service is the only writer, and the unprivileged session daemon
submits records to it over the system bus (ADR-5, ADR-11).

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT",
"SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this
document are to be interpreted as described in RFC 2119.

## Consumers

- **The audit service** (`famulus-auditd`, a root system service) implements
  this interface on the **system bus**: bus name `org.famulus.Audit1`, object
  path `/org/famulus/Audit1`, interface `org.famulus.Audit1`. It is the sole
  process that opens audit files for writing.
- **famulus-agentd** calls `Append` once per agent action (after the action's
  outcome is known) and is the only permitted appender.
- **famulus-gui** calls `Query` to render the audit timeline and `Verify` to
  show chain health. It never reads the files directly.

## Files

| File | Purpose |
| --- | --- |
| `org.famulus.Audit1.xml` | D-Bus introspection XML (the machine-readable interface definition) |
| `append-request.schema.json` | JSON Schema (draft 2020-12) for the `Append` `record_json` payload |
| `validate_append_request.py` | Validator for `Append` payload files (schema + no floats) |
| `fixtures/` | Valid and invalid `Append` payloads |
| `test_audit_service.py` | Contract lock tests (stdlib `unittest`) |
| `README.md` | This normative specification |

## Running the validator and tests

From the repository root:

```sh
.venv/bin/python dbus-audit/validate_append_request.py dbus-audit/fixtures/valid-tier0.json
.venv/bin/python -m unittest discover -s dbus-audit -v
```

The validator exits 0 when every payload is valid, 1 on validation failure,
and 2 on usage error.

## Interface summary

| Method | Signature | Purpose |
| --- | --- | --- |
| `Append` | `(in s record_json) -> (out s ts, out s hash)` | Append one record to the caller's chain |
| `Query` | `(in s conversation_id, in s after_event_id, in u limit) -> (out s records_ndjson, out b more)` | Page through the caller's own records |
| `Verify` | `() -> (out b ok, out u record_count, out s head_hash, out s message)` | Verify the caller's chain against the latest anchor |

The interface has **no signals and no properties**. A system-bus signal is
visible to every user, so a `RecordAppended` broadcast would leak one user's
activity to the others. Live updates reach the GUI through famulus-agentd's
session-bus signals (C2). The GUI calls `Query` for history.

## Chains and storage

- The service MUST keep **one independent C1 hash chain per Unix uid**, at
  `/var/log/famulus/audit/uid-<uid>/audit.ndjson` (covered by the C5
  `hard_deny` floor `/var/log/famulus/audit/**`). Directories are
  `root:root 0700`, files `root:root 0600`, and files SHOULD carry the
  append-only attribute (`chattr +a`) where the filesystem supports it.
- The caller's uid MUST be taken from the bus connection credentials
  (`GetConnectionCredentials` → `UnixUserID`). No method accepts a uid, so a
  caller can only ever touch its own chain.
- The record format, canonical JSON, genesis rule, and hashing are exactly
  C1 (`audit-log/HASHING.md`). C7 adds no fields.

## Append

`record_json` MUST be a JSON object valid against
`append-request.schema.json`, which is the C1 record **without** the members
the writer assigns:

| Member | Assigned by | Rule |
| --- | --- | --- |
| `ts` | service | its own clock, RFC 3339 UTC with `Z`, at append time |
| `prev_hash` | service | `hash` of the caller's current chain head (genesis: 64 × `0`) |
| `hash` | service | per C1 HASHING.md over the completed record |

The service MUST:

1. reject a payload that fails the schema or contains a float anywhere
   (`Error.InvalidRecord`). This also covers a client that tries to supply
   `ts`/`prev_hash`/`hash`, because the schema is closed.
2. reject an `event_id` already present in the caller's chain
   (`Error.DuplicateEvent`). `event_id` is client-generated (UUIDv7) because
   it must exist *before* the action: it is embedded in the C4 snapshot tag
   and `snapshot_ref`.
3. serialize appends per chain, write the canonical-JSON line, `fsync`, and
   only then reply with the assigned `ts` and `hash`.
4. anchor the new head `hash` outside the chain file. It SHOULD write a
   systemd journal entry with `FAMULUS_AUDIT_UID=<uid>` and
   `FAMULUS_AUDIT_HEAD=<hash>`, and MAY also write a root-owned anchor file
   under `/var/lib/famulus/audit/`. This is the external anchoring that C1
   HASHING.md section 7 requires for tail-truncation detection.

Because the log is append-only, a rollback never edits the original record.
famulus-agentd appends a **new** record (`actor` `"user"` or `"system"`, same
`snapshot_ref`, `result` `"rolled-back"`).

## Authorization of Append

The AI runs as the same uid as famulus-agentd. Without a further check, any
tool process (for example a `Bash` call running `busctl`) could append
forged records to the user's chain. C7 closes this with cgroup identity:

- The service MUST accept `Append` only from a peer whose process belongs to
  that user's `famulus-agentd.service` unit cgroup (resolved from the peer's
  pidfd/PID via `/proc/<pid>/cgroup`, preferring a pidfd from
  `GetConnectionCredentials` → `ProcessFD` to avoid PID-reuse races).
  Everything else gets `Error.AccessDenied`.
- famulus-agentd MUST therefore spawn every supervised `claude` CLI process
  **outside** its own unit cgroup, in a transient user scope (for example
  `systemd-run --user --scope --unit famulus-cli-<conversation-id>`). The
  CLI, its MCP servers, and every tool process then fall outside
  `famulus-agentd.service` and cannot append.
- `Query` and `Verify` are allowed for any local caller. They only ever
  return the caller's own chain.

Residual risk (documented, accepted for v1): code running *inside*
famulus-agentd's cgroup can append for that uid. The chain stays
tamper-evident against modification, deletion, and reordering by anyone
except root.

## Query

Returns complete C1 records (including `ts`, `prev_hash`, `hash`) from the
caller's chain, in chain order, as canonical-JSON NDJSON (one record per
LF-terminated line; an empty string when there are no matches).

- `conversation_id`: filter, or `""` for all conversations.
- `after_event_id`: resume after this record, or `""` to start at genesis.
  An id that is not in the caller's chain raises `Error.NotFound`.
- `limit`: maximum number of records. `0` means the service default. The
  service MUST NOT return more than 1000 records per call.
- `more`: true when further matching records exist after the last one
  returned. Pass that record's `event_id` as `after_event_id` to continue.

## Verify

Verifies the caller's chain end-to-end per C1 and compares its head with
the latest anchor. `ok` is true only when both checks pass. `head_hash` is
the last record's `hash` (64 × `0` for an empty chain). `message` is empty
when `ok`, otherwise a human-readable diagnosis naming the first failing
line or the anchor mismatch.

## Errors

Methods MUST fail only with these D-Bus error names:

- `org.famulus.Audit1.Error.InvalidRecord`: `record_json` fails the schema
  or contains a float.
- `org.famulus.Audit1.Error.DuplicateEvent`: `event_id` already in the
  caller's chain.
- `org.famulus.Audit1.Error.AccessDenied`: `Append` from outside
  `famulus-agentd.service`.
- `org.famulus.Audit1.Error.NotFound`: unknown `after_event_id`.
- `org.famulus.Audit1.Error.Failed`: generic failure (I/O, corrupt chain
  that prevents appending).

## Stability

Frozen at tag contracts-v1. Changes require an ADR, maintainer review, and a new frozen tag; already-frozen tags are never rewritten.
