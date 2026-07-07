# famulus-contracts

famulus-contracts is the single source of truth for the six Famulus interface contracts, C1–C6, that bind every other repo in the project together. It holds the JSON Schemas, D-Bus introspection XML, YAML manifest and policy shapes, and the Claude stream-json → D-Bus event map. Contracts are versioned and released as frozen git tags; all other repos build against tag `contracts-v1`. This repo is deliberately licensed under Apache-2.0 (SPDX: `Apache-2.0`) — permissive rather than copyleft — so that anyone, including third-party tools, can implement the contracts without copyleft obligations.

Famulus is an open-source, AI-native atomic Linux distribution built on Fedora Atomic, whose chat app and GNOME Shell panel supervise the unmodified official `claude` CLI and control the system through curated MCP servers, skills, polkit permission tiers, snapshot-before-mutate rollback, and a hash-chained audit log. Every one of those moving parts talks to the others across a contract defined here: the audit-log schema, the `org.famulus.Agent1` and `org.famulus.Snapshot1` D-Bus interfaces, the skill manifest, the permission/tier policy, and the stream-json event map. Keeping those definitions in one small, frozen, permissively licensed repo is what lets the rest of the project evolve independently without drifting apart.

## The six contracts

| ID | Directory | Contract |
|----|-----------|----------|
| C1 | [`audit-log/`](audit-log/) | JSON Schema for one audit-log record plus the SHA-256 hash-chain spec (`HASHING.md`) and a reference chain verifier. |
| C2 | [`dbus-agent/`](dbus-agent/) | `org.famulus.Agent1` / `org.famulus.Conversation1` D-Bus introspection XML — the session daemon's conversation API. |
| C3 | [`skill-manifest/`](skill-manifest/) | Schema for the `manifest.yaml` that ships next to each `SKILL.md`, with example manifests. |
| C4 | [`dbus-snapshot/`](dbus-snapshot/) | `org.famulus.Snapshot1` D-Bus introspection XML and the `snapshot_ref` format spec. |
| C5 | [`tier-policy/`](tier-policy/) | Machine-readable permission/tier policy format, the shipped default policy, and the hard-deny floor. |
| C6 | [`event-map/`](event-map/) | Claude stream-json → C2 D-Bus signal event map: normative table, synthetic NDJSON fixtures, reference mapper. |

**Stability:** frozen at `contracts-v1`. Changes require an ADR, maintainer review, and a new frozen tag; already-frozen tags are never rewritten.

## Validating

```sh
just validate   # bootstraps .venv, then runs every schema meta-check, validator, and test suite
```

Each contract directory also documents how to run its own validator and tests in isolation.

Governance, the master plan, ADRs and the contribution policy live in [famulus-meta](../famulus-meta).
