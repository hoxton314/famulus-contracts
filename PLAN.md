# PLAN.md — famulus-contracts

> Repo role: **single source of truth for the seven frozen interface contracts (C1–C7; C7 audit-writer added during freeze review)**. Every other repo builds against the tag `contracts-v1`. License: Apache-2.0.
> Master plan: `famulus-meta/famulus-execution-plan.md` (Part 0 ADRs, Part 2 phases).

## Scope
Schemas, D-Bus introspection XML, policy files, event-map spec, fixtures, and validators. **Non-goals:** any runtime implementation (daemon, GUI, skills live elsewhere).

## Contracts owned here

| ID | Contract | Artifact | Status |
|----|----------|----------|--------|
| C1 | Audit-log record schema + hash-chain spec | `audit-log/` (JSON Schema 2020-12, HASHING.md, chain validator) | in PR (phase0-contracts) |
| C2 | `org.famulus.Agent1` / `org.famulus.Conversation1` D-Bus interface | `dbus-agent/` (introspection XML + parse test) | in PR (phase0-contracts) |
| C3 | Skill `manifest.yaml` schema | `skill-manifest/` (schema, 2 example manifests, validator) | in PR (phase0-contracts) |
| C4 | `org.famulus.Snapshot1` D-Bus interface | `dbus-snapshot/` (XML, snapshot_ref format spec) | in PR (phase0-contracts) |
| C5 | Permission/tier policy format + default policy | `tier-policy/` (YAML schema, default policy, hard-deny list, validator) | in PR (phase0-contracts) |
| C6 | Claude stream-json → D-Bus event map | `event-map/` (Markdown spec, ≥6 NDJSON fixtures, mapping table) | in PR (phase0-contracts) |

## Key requirements (from ADRs)
- **C1:** fields `{ts, event_id(uuidv7), conversation_id, actor, tool, input_redacted, decision, tier, snapshot_ref, deployment_before, result, prev_hash, hash}`; canonical JSON = sorted keys, no whitespace, UTF-8; `hash = SHA256(prev_hash || canonical(record_without_hash))` (ADR-5).
- **C2:** methods `CreateConversation`, per-conversation `SendMessage/Cancel/GetTranscript/Close`, `RespondPermission`; signals `ResponseDelta, ToolCall, ToolResult, PermissionRequest, ResponseComplete, ConversationError`; properties `DaemonVersion, CliVersion, AuthMethod` (ADR-1/2/3).
- **C3:** `{name, version, tier, mutates_system, polkit_actions[], files_touched[], network_access, description}`; `mutates_system: true` ⇒ snapshot mandatory (ADR-6).
- **C4:** `Create(subvols, tag)→snapshot_ref`, `Restore`, `List`, `Prune`; ref format `famulus-snap/<event_id>/<subvol>@<unix_ts>`; Create MUST record rpm-ostree deployment digest (ADR-4).
- **C5:** pattern→tier→behavior entries; hard-deny: writes to `/var/log/famulus/audit/**`, `~/.claude/.credentials.json` (ADR-11, ADR-5).
- **C6:** `system/init`→store session_id; `stream_event .event.delta.text`→`ResponseDelta`; assistant `tool_use`→`ToolCall`; tool results→`ToolResult`; `result`→`ResponseComplete`. Mark the stdin user-turn envelope `{"type":"user","message":{...}}` as **inferred** (Anthropic issue #24594) — discrepancies found downstream feed a `contracts-v1.1` revision.

## Process
1. All contracts land in a single PR `phase0-contracts` (sequential, one agent).
2. Human review → merge → tag **`contracts-v1`** → announce to all repos.
3. Breaking changes after the freeze require a new tag (`contracts-v1.1`) + compat notes + sign-off from maintainer; CI runs schema-compat checks blocking silent breaks.

## Definition of done (Phase 0 gate)
- `just validate` runs all validators + tests green; every schema passes its meta-schema.
- Root README lists all seven contracts, one line each, stability note "frozen at contracts-v1".
