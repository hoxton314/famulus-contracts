# C6 — Claude stream-json → D-Bus event map

Contract C6 defines how famulus-agentd translates the NDJSON stream of the
**unmodified** official `claude` CLI into the D-Bus signals of the C2
`org.famulus.Conversation1` interface. The CLI is launched as:

```
claude -p --input-format stream-json --output-format stream-json --verbose \
  --include-partial-messages --permission-prompt-tool mcp__famulus_broker__approve
```

**Consumers:** famulus-agentd (implements this mapping), the Famulus chat app
and GNOME Shell extension (consume the resulting C2 signals), and any tooling
that replays or audits conversation transcripts.

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHOULD**, **SHOULD
NOT**, and **MAY** in this document are to be interpreted as described in
RFC 2119.

## Files

| File | Purpose |
|------|---------|
| `README.md` | This normative specification (the mapping table below is the contract) |
| `map_events.py` | Reference mapper — an executable specification of the table, not runtime code |
| `fixtures/*.ndjson` | Synthetic stream-json scenes (`01`–`05` stdout direction, `06` stdin direction) |
| `fixtures/README.md` | Fixture inventory and provenance notes |
| `recorded/cli-2.1.284/` | Sanitized recordings of the real `claude` 2.1.284 (stdout, stdin, broker MCP exchange) + expected emissions — see `recorded/README.md` |
| `expected/*.json` | For each stdout fixture, the exact ordered D-Bus signal emissions |
| `test_event_map.py` | Unit tests binding fixtures, expected emissions, and the reference mapper together |

## Lifecycle

1. famulus-agentd spawns one long-lived `claude` process per conversation
   with the command line above, and holds its stdin/stdout pipes.
2. On each C2 `SendMessage`, the daemon writes one user envelope line to the
   CLI's stdin (INPUT direction below) and generates a fresh **`turn_id`**.
   The `turn_id` is **daemon-generated per `SendMessage`** — the CLI has no
   turn concept and never sees or emits it. Every signal the daemon emits
   for that turn carries this `turn_id`.
3. The daemon reads the CLI's stdout line by line. Each non-empty line MUST
   parse as a single JSON object; the daemon maps it per the table below and
   emits the corresponding `org.famulus.Conversation1` signals in stream
   order.
4. The `session_id` arrives in the `system`/`init` line and again in every
   `result` line. The daemon MUST store it and include it in the
   `ResponseComplete` `result_json` payload. `system`/`init` is emitted at the
   start of **every turn**, not once per process; storing it MUST be
   idempotent (the `session_id` stays constant within one process).
5. On C2 `Cancel`, the daemon writes a `control_request` interrupt envelope
   to stdin (INPUT direction). The CLI acknowledges with a `control_response`
   line carrying the same `request_id`, then ends the turn with a `result`
   line (`is_error: true`; observed `subtype: "error_during_execution"`,
   `terminal_reason: "aborted_streaming"`). The process stays alive and
   accepts the next user envelope — `Cancel` MUST NOT respawn the CLI.

## The mapping table

Discriminators use jq-style paths into the parsed NDJSON line. "daemon"
means the value is generated or resolved by famulus-agentd, not read from
the stream. Signal arguments not listed for a row are absent because the row
emits no signal.

| Stream-json event (discriminating fields) | D-Bus signal emitted | Field mapping | Status |
|---|---|---|---|
| `.type == "system"` and `.subtype == "init"` | none — internal | Daemon MUST store `.session_id` (idempotently — repeats every turn); it MAY store `.model`, `.tools`, `.mcp_servers`, `.permissionMode`, `.apiKeySource`, `.claude_code_version`, `.capabilities` for diagnostics/`GetTranscript` | VERIFIED |
| `.type == "system"`, any other `.subtype` (observed: `status`, `thinking_tokens`) | ignored in v1 | — | VERIFIED |
| `.type == "stream_event"`, `.event.type == "content_block_delta"`, `.event.delta.type == "text_delta"` | `ResponseDelta` | `turn_id` ← daemon; `text_chunk` ← `.event.delta.text` | VERIFIED |
| `.type == "stream_event"`, `.event.type == "content_block_delta"`, `.event.delta.type` other than `text_delta` (observed: `input_json_delta`, `thinking_delta`, `signature_delta`) | ignored in v1 | — (buffered `tool_use` input arrives complete in the `assistant` message; thinking is not surfaced in v1) | VERIFIED |
| `.type == "stream_event"`, `.event.type` ∈ {`message_start`, `content_block_start`, `content_block_stop`, `message_delta`, `message_stop`} | ignored in v1 | — | VERIFIED |
| `.type == "assistant"`, per `.message.content[]` block with `.type == "tool_use"` | `ToolCall` (one per block, in array order) | `turn_id` ← daemon; `tool_use_id` ← block `.id`; `tool_name` ← block `.name`; `input_json` ← canonical JSON of block `.input`; `tier` ← C5 policy resolution (NOT from the stream). Daemon MUST record block `.id` → `.name` for later `ToolResult` correlation | VERIFIED |
| `.type == "assistant"`, per `.message.content[]` block with `.type == "text"` | none | Text was already streamed as `text_delta` chunks. If no partial deltas were streamed for this message (e.g. `--include-partial-messages` absent), the daemon SHOULD emit one `ResponseDelta` per text block carrying the full `.text` | VERIFIED |
| `.type == "user"`, per `.message.content[]` block with `.type == "tool_result"` | `ToolResult` (one per block, in stream order) | `turn_id` ← daemon; `tool_use_id` ← `.tool_use_id`; `tool_name` ← stored correlation for `.tool_use_id`; `result_json` ← `.content` normalized (a string is kept verbatim; a list of content blocks is canonical-JSON-serialized); `is_error` ← `.is_error` (absent means `false`) | VERIFIED |
| `.type == "result"` (any `.subtype`) | `ResponseComplete` | `turn_id` ← daemon; `result_json` ← canonical JSON of `{session_id, total_cost_usd, is_error, num_turns}` plus optional passthrough of `duration_ms`, `duration_api_ms`, `usage`, `subtype`, `terminal_reason` when present — shape per C2 `dbus-agent/response-complete.schema.json` | VERIFIED |
| `.type == "control_response"` | none — internal | Acknowledges a stdin `control_request`; `.response.request_id` echoes it. Daemon MAY use it to confirm `Cancel` | VERIFIED |
| `.type == "rate_limit_event"` | ignored in v1 (SHOULD log) | — (`.rate_limit_info` carries subscription-window status; candidate for a v1.x signal) | VERIFIED |
| INPUT (stdin): `{"type":"user","message":{"role":"user","content":"text"}}` | none — input direction | Daemon writes one such line per C2 `SendMessage` | VERIFIED |
| INPUT (stdin): `{"type":"control_request","request_id":"...","request":{"subtype":"interrupt"}}` | none — input direction | Daemon writes one such line on C2 `Cancel` | VERIFIED |

Additional normative rules:

- Signals for a single NDJSON line MUST be emitted in the order given above
  (e.g. two `tool_use` blocks yield two `ToolCall` signals in array order).
- A stdout line with an unrecognized top-level `.type` MUST be ignored (and
  SHOULD be logged) in v1; it MUST NOT raise `ConversationError`.
- **Canonical JSON** (for `input_json` and `result_json`): the UTF-8 string
  produced by serializing with keys sorted by Unicode code point, no
  insignificant whitespace (`","` and `":"` separators), and non-ASCII
  characters NOT escaped — i.e. Python
  `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
- `tier` is a uint32 (D-Bus type `u`) with value 0, 1, or 2, resolved from
  the C5 tier policy by tool name/input — never taken from the stream.

## PermissionRequest — no stream-json source

The `PermissionRequest(s request_id, s turn_id, s tool_use_id, s tool_name,
s input_json, u tier)` signal has **no row in the table above because it has no stream-json
source**. It originates out-of-band from the
`mcp__famulus_broker__approve` MCP tool call: when the CLI needs permission,
it invokes that tool (per `--permission-prompt-tool`); the broker forwards
the request to famulus-agentd, which emits `PermissionRequest` and blocks
the MCP reply until C2 `RespondPermission` is called (or the request times
out), then emits `PermissionResolved(request_id, behavior)`.

Broker wire shape (VERIFIED against CLI 2.1.284, `recorded/cli-2.1.284/*.broker.ndjson`;
Anthropic documents this only for the SDK, issue #1175):

- MCP `tools/call` request: `params.name == "approve"`, `params.arguments ==
  {"tool_name": "...", "input": {...}, "tool_use_id": "toolu_..."}`;
  `params._meta["claudecode/toolUseId"]` repeats the id. `tool_use_id`
  equals the id of the `tool_use` block already seen on stdout, which is how
  the daemon fills `PermissionRequest.tool_use_id`/`turn_id`.
- MCP result: one `text` content block whose text is the JSON decision:

```json
{"behavior": "allow", "updatedInput": {...}}
{"behavior": "deny", "message": "..."}
```

`updatedInput` replaces the tool input verbatim (verified: a rewritten Bash
`command` is what runs). A deny surfaces on stdout as a `tool_result` with
`is_error: true` and `content` equal to `message`, and in the turn's
`result.permission_denials`.

C1 `decision` values map to the outcome as follows: policy `auto-allow` →
`"auto-allow"`; prompt answered yes → `"user-allow"`; prompt answered no →
`"user-deny"`; deny rule or hard-deny → `"hook-deny"`.

## ConversationError — no stream-json source

`ConversationError(s message)` also has no stream-json source. The daemon
MUST emit it on **process-level failure** of the supervised CLI:

- the CLI exits with a non-zero status mid-turn;
- a stdout line is not parseable as JSON;
- stdout reaches EOF mid-turn.

A `result` line with `is_error: true` is **NOT** a `ConversationError` — it
is a completed (failed) turn and surfaces via `ResponseComplete` with
`is_error: true` inside `result_json`.

## Reference mapper and fixtures

`map_events.py` is the executable form of the table: `map_line(state,
line_obj, turn_id)` returns the ordered signal emissions for one stdout
line. It exists so the fixtures and the table are machine-checked against
each other; it is NOT runtime code. Because the real `tier` comes from C5
policy resolution, the reference mapper uses a fixed test-policy stub
(documented in the module docstring): tool names containing `wallpaper` →
tier 0, `Bash` → tier 2, everything else → tier 2.

Fixtures under `fixtures/` are **SYNTHETIC** (hand-written, minimal,
readable); fixtures under `recorded/` are **sanitized real CLI output**.
Both are bound by `test_event_map.py`. See `fixtures/README.md` and
`recorded/README.md`.

Run the reference mapper (works from any CWD; from the repo root):

```
.venv/bin/python event-map/map_events.py event-map/fixtures/01-init-and-text-turn.ndjson --turn-id T1
```

Run the tests (from the repo root):

```
.venv/bin/python -m unittest discover -s event-map -v
```

## Verification status

- **VERIFIED** means observed against a real `claude` binary — currently
  **2.1.284** (recordings in `recorded/cli-2.1.284/`): all stdout rows, both
  stdin envelopes (user turn, `control_request` interrupt — previously
  inferred from Agent SDK analogy, issue #24594), and the
  `--permission-prompt-tool` request/reply shape (issue #1175).
- These shapes remain undocumented by Anthropic for the raw CLI. The daemon
  MUST pin the CLI version and re-run a recording against every new pinned
  version (famulus-agentd W2.E3.T3 / W9.E3.T1); a new
  `recorded/cli-<version>/` directory is added per verified version.
- Discrepancies found downstream (once famulus-agentd runs against the real
  CLI) feed a `contracts-v1.1` revision per PLAN.md; already-frozen tags are
  never rewritten.

## Stability

Frozen at tag contracts-v1. Changes require an ADR, maintainer review, and a new frozen tag; already-frozen tags are never rewritten.
