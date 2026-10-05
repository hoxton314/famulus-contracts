# C1 audit-log hash chain — normative specification

This document specifies the hash chain of the Famulus audit log (contract
C1). The key words MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY in this
document are to be interpreted as described in RFC 2119.

The record shape itself is defined by
[`audit-record.schema.json`](audit-record.schema.json); this document
defines how records are serialized, hashed, chained, and stored.

## 1. Canonical JSON serialization

Wherever hashing is involved, a record MUST be serialized as canonical
JSON, defined byte-precisely as: the UTF-8 encoding of the JSON text in
which

- object keys are sorted by Unicode code point,
- there is no insignificant whitespace (item separator `,`, key separator
  `:`, no spaces, no newlines), and
- non-ASCII characters are NOT escaped (they appear as literal UTF-8, not
  `\uXXXX` sequences).

The reference definition is the following Python expression; conforming
implementations MUST produce byte-identical output:

```python
json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
```

## 2. Floats are forbidden

Floats are forbidden anywhere in a record: canonical float serialization
is not defined in v1. All numbers in a record MUST be integers. Writers
MUST NOT emit floats; verifiers MUST reject any record containing a float
(including inside `input_redacted`).

## 3. Record hash

Each record's `hash` member is computed as:

```
hash = SHA256( ascii_bytes(prev_hash_lowercase_hex)
               || canonical_json_bytes(record WITHOUT its "hash" member,
                                       but WITH "prev_hash") )
```

encoded as lowercase hexadecimal, where `||` denotes byte concatenation
and `ascii_bytes(prev_hash_lowercase_hex)` is the 64 ASCII bytes of the
lowercase-hex `prev_hash`.

Note that `prev_hash` therefore enters the hash input twice — once as the
64-byte ASCII prefix and once as an ordinary member of the canonicalized
record. This is intentional, per ADR-5.

The reference implementation is `record_hash(prev_hash, record_sans_hash)`
in [`validate_chain.py`](validate_chain.py).

## 4. Genesis rule

The first record of a log MUST have a `prev_hash` of exactly 64 ASCII `0`
characters:

```
0000000000000000000000000000000000000000000000000000000000000000
```

## 5. Chain rule

For every N > 1, record N's `prev_hash` MUST be byte-equal to record
N-1's `hash`.

## 6. File format

The audit log is an append-only NDJSON file: one record per line, UTF-8
encoded, lines terminated by LF (`\n`). Records MUST only ever be
appended; existing lines MUST NOT be modified, reordered, or deleted.

Lines SHOULD be written in canonical form (Section 1). However, verifiers
MUST parse each line as JSON and re-canonicalize the parsed record before
hashing, rather than comparing or hashing raw line bytes — a
non-canonically formatted line with correct content still verifies.

## 7. Tamper evidence: properties and limitations

Properties:

- Modification of any member of any record changes that record's
  recomputed hash and breaks verification at that line.
- Reordering, deleting, or inserting records breaks the `prev_hash`
  linkage (and the genesis rule, if the first record is affected).
- Because `prev_hash` is part of both the hash input prefix and the
  hashed record body, a record cannot be re-linked to a different
  predecessor without changing its own hash.

Limitations:

- Truncation of the TAIL of the log (removing the last K records) is NOT
  detectable from the file alone: the remaining prefix is still a valid
  chain. Detecting tail truncation requires the latest `hash` to be
  anchored externally.
- The chain proves integrity, not authenticity: anyone who can rewrite
  the whole file can recompute a consistent chain. External anchoring
  also mitigates this.

Therefore the audit writer (famulus-auditd, contract C7) SHOULD anchor
the latest `hash` outside the log itself (for example in a separate
root-owned location, systemd journal entry, or remote store), and
auditors SHOULD compare the final record's `hash` against the most
recent anchor.

## 8. Worked example (test vector)

A complete genesis record (keys shown sorted, pretty-printed for
readability only):

```json
{
  "actor": "agent",
  "conversation_id": "b3f9c2e8-4d17-4f6a-9c05-2e8b7a1d4c66",
  "decision": "auto-allow",
  "deployment_before": null,
  "event_id": "019f3ce3-fc82-7a1c-8f3b-1d2e4a6c8b0f",
  "hash": "f87b9447c99a26bd0fa44f49a1dc073527bd1cdd9964fca29a1286880d075b3c",
  "input_redacted": {
    "uri": "file:///home/user/Pictures/aurora.png"
  },
  "prev_hash": "0000000000000000000000000000000000000000000000000000000000000000",
  "result": "ok",
  "snapshot_ref": null,
  "tier": 0,
  "tool": "mcp__famulus_desktop__wallpaper_set",
  "ts": "2026-07-07T14:03:22.114Z"
}
```

Step 1 — remove the `hash` member and canonicalize (Section 1). The
canonical serialization, on one line:

```
{"actor":"agent","conversation_id":"b3f9c2e8-4d17-4f6a-9c05-2e8b7a1d4c66","decision":"auto-allow","deployment_before":null,"event_id":"019f3ce3-fc82-7a1c-8f3b-1d2e4a6c8b0f","input_redacted":{"uri":"file:///home/user/Pictures/aurora.png"},"prev_hash":"0000000000000000000000000000000000000000000000000000000000000000","result":"ok","snapshot_ref":null,"tier":0,"tool":"mcp__famulus_desktop__wallpaper_set","ts":"2026-07-07T14:03:22.114Z"}
```

Step 2 — the exact hash input is the 64 ASCII `0` bytes of the genesis
`prev_hash` immediately followed by the canonical bytes above (shown here
wrapped for readability; the actual input is one unbroken byte string
with no separator):

```
0000000000000000000000000000000000000000000000000000000000000000{"actor":"agent","conversation_id":"b3f9c2e8-4d17-4f6a-9c05-2e8b7a1d4c66","decision":"auto-allow","deployment_before":null,"event_id":"019f3ce3-fc82-7a1c-8f3b-1d2e4a6c8b0f","input_redacted":{"uri":"file:///home/user/Pictures/aurora.png"},"prev_hash":"0000000000000000000000000000000000000000000000000000000000000000","result":"ok","snapshot_ref":null,"tier":0,"tool":"mcp__famulus_desktop__wallpaper_set","ts":"2026-07-07T14:03:22.114Z"}
```

Step 3 — SHA-256 of that input, lowercase hex:

```
f87b9447c99a26bd0fa44f49a1dc073527bd1cdd9964fca29a1286880d075b3c
```

The stored NDJSON line (canonical form, now including `hash`) is:

```
{"actor":"agent","conversation_id":"b3f9c2e8-4d17-4f6a-9c05-2e8b7a1d4c66","decision":"auto-allow","deployment_before":null,"event_id":"019f3ce3-fc82-7a1c-8f3b-1d2e4a6c8b0f","hash":"f87b9447c99a26bd0fa44f49a1dc073527bd1cdd9964fca29a1286880d075b3c","input_redacted":{"uri":"file:///home/user/Pictures/aurora.png"},"prev_hash":"0000000000000000000000000000000000000000000000000000000000000000","result":"ok","snapshot_ref":null,"tier":0,"tool":"mcp__famulus_desktop__wallpaper_set","ts":"2026-07-07T14:03:22.114Z"}
```

This record is also line 1 of
[`fixtures/valid-chain.ndjson`](fixtures/valid-chain.ndjson) and is
reproduced as a test vector in `test_audit_log.py`.
