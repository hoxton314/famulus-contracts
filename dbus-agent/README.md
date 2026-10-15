# C2 — `org.famulus.Agent1` D-Bus interface (dbus-agent)

Contract C2 defines the D-Bus surface through which the Famulus session daemon
(famulus-agentd) re-exposes supervised `claude` CLI processes on the **session
bus**. famulus-agentd is the sole implementer. Consumers are the GTK4/libadwaita
chat app, the GNOME Shell panel indicator, the famulus permission-broker MCP
server, and any third-party tooling that wants to talk to the agent.

The key words MUST, MUST NOT, REQUIRED, SHALL, SHALL NOT, SHOULD, SHOULD NOT,
RECOMMENDED, MAY, and OPTIONAL in this document are to be interpreted as
described in RFC 2119.

## Files

| File | Purpose |
| --- | --- |
| `org.famulus.Agent1.xml` | Introspection XML for the daemon entry-point interface. |
| `org.famulus.Conversation1.xml` | Introspection XML for per-conversation objects. |
| `response-complete.schema.json` | JSON Schema (draft 2020-12) for the `ResponseComplete` signal's `result_json` payload. |
| `validate_response_complete.py` | CLI validator for `result_json` payload files. |
| `test_introspection.py` | Structural-lock unittest suite for this contract. |

## Validation and tests

Run from the repo root:

```sh
gdbus-codegen --interface-info-body --output /dev/null dbus-agent/org.famulus.Agent1.xml
gdbus-codegen --interface-info-body --output /dev/null dbus-agent/org.famulus.Conversation1.xml
.venv/bin/python dbus-agent/validate_response_complete.py PAYLOAD.json [PAYLOAD.json ...]
.venv/bin/python -m unittest discover -s dbus-agent -v
```

The validator exits 0 when every payload is valid, 1 on validation failure, and
2 on usage error.

## Bus topology

- Bus name: `org.famulus.Agent1` on the **session bus**.
- `org.famulus.Agent1` object: `/org/famulus/Agent1`.
- Conversation objects (interface `org.famulus.Conversation1`), created by
  `CreateConversation`: `/org/famulus/Agent1/conversations/<id>`, where `<id>`
  MUST match `[0-9A-Za-z_]+`.
- The daemon MUST implement the standard `org.freedesktop.DBus.ObjectManager`
  interface on `/org/famulus/Agent1`. Clients (chat app sidebar, Shell panel)
  enumerate conversations with `GetManagedObjects` and track them via
  `InterfacesAdded`/`InterfacesRemoved`; there is deliberately no bespoke
  `ListConversations` method.
- Persistence (ADR-2): on start the daemon MUST re-export every persisted,
  non-closed conversation under its original `<id>`, without spawning a CLI
  process. The process is spawned lazily on the first `SendMessage`, with
  `--resume <SessionId>` when `SessionId` is non-empty.

## Lifecycle

`CreateConversation` spawns exactly one supervised `claude` CLI process
(`claude -p --input-format stream-json --output-format stream-json --verbose
--include-partial-messages --permission-prompt-tool
mcp__famulus_broker__approve`) and exports a new `org.famulus.Conversation1`
object; the method returns that object's path. `SendMessage` returns a
daemon-generated `turn_id` immediately and the response streams asynchronously
via signals carrying that `turn_id`. `Cancel` interrupts the in-flight turn (it
is a no-op when idle). `GetTranscript` returns the accumulated transcript as
JSON: an array of message objects in claude stream-json `"message"` shape.
`Close` terminates the CLI process and removes the conversation object from the
bus. `Cancel` interrupts via the stdin interrupt envelope (C6) and does NOT
restart the CLI process; the turn ends with `ResponseComplete` carrying
`is_error: true` (and, when reported, `subtype`/`terminal_reason`).

`turn_id` is daemon-generated and opaque — the CLI has no such concept; the
daemon mints one per `SendMessage` so consumers can correlate signals with
turns. `tool_use_id` is the CLI's `tool_use` block id (`toolu_…`); it
correlates `ToolCall`, `PermissionRequest`, and `ToolResult` for the same tool
invocation — `tool_name` alone is ambiguous when a turn calls the same tool
twice. `tier` in `ToolCall` and `PermissionRequest` is the permission tier
resolved from the C5 tier policy (uint32; 0 = read-only/no-auth, 1 =
user-authenticated, 2 = admin-authenticated). `input_json` and `result_json`
arguments are canonical-JSON-serialized strings: the UTF-8 output of Python's
`json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.

## Signals

**`ResponseDelta(s turn_id, s text_chunk)`** — a streamed chunk of assistant
text for the given turn, sourced from the CLI's partial-message stream events.
Consumers MUST concatenate chunks per `turn_id` in emission order to
reconstruct the response text.

**`ToolCall(s turn_id, s tool_use_id, s tool_name, s input_json, u tier)`** — the CLI began a
tool invocation. `input_json` is the canonical-JSON tool input; `tier` is the
C5 tier resolved for this tool call.

**`ToolResult(s turn_id, s tool_use_id, s tool_name, s result_json, b is_error)`** — a tool
invocation finished. `result_json` is the canonical-JSON tool result;
`is_error` is true when the tool failed or was denied.

**`PermissionRequest(s request_id, s turn_id, s tool_use_id, s tool_name, s input_json, u tier)`** — the
permission broker needs a user decision for a tool call. `turn_id` is the
in-flight turn; `tool_use_id` matches the preceding `ToolCall`. The broker's
reply to the CLI stays blocked until `RespondPermission` is called with this
`request_id` or the request times out (see below). Until it is settled, the
request is also listed in the `PendingPermissions` property.

**`PermissionResolved(s request_id, s behavior)`** — a pending request was
settled, by any client's `RespondPermission` or by timeout (`behavior` is
`"allow"` or `"deny"`; a timeout is `"deny"`). Several clients (chat app,
Shell panel) may show the same request; each MUST dismiss its dialog on this
signal.

**`ResponseComplete(s turn_id, s result_json)`** — the turn finished.
`result_json` MUST validate against `response-complete.schema.json`. Per-turn
API errors surface here with `is_error` true — they do NOT use
`ConversationError`.

**`ConversationError(s message)`** — reserved for process-level failures only:
CLI crash, unparseable stream-json, or unexpected EOF on the CLI's stdout.
After `ConversationError`, the conversation object may no longer be usable.

## Properties (Conversation1)

All four emit `org.freedesktop.DBus.Properties.PropertiesChanged` when they
change.

- **`Id` (s)** — stable conversation id: the last path element and the
  directory name under `~/.local/share/famulus/conversations/`.
- **`SessionId` (s)** — the CLI `session_id` used for `--resume`; `""` until
  the CLI has reported one.
- **`Busy` (b)** — true from `SendMessage` until the matching
  `ResponseComplete` or `ConversationError`.
- **`PendingPermissions` (a(sssssu))** (v1.1) — the conversation's permission
  requests that are not settled yet, oldest first. Each entry is
  `(request_id, turn_id, tool_use_id, tool_name, input_json, tier)`, with
  the same values the `PermissionRequest` signal carried. See
  [Late clients](#late-clients-pendingpermissions).

## Permission flow

The claude CLI is started with
`--permission-prompt-tool mcp__famulus_broker__approve`. When the CLI asks for
permission to run a tool, the famulus broker MCP server forwards the request to
famulus-agentd, which emits `PermissionRequest(request_id, turn_id,
tool_use_id, tool_name, input_json, tier)` on the conversation object and
blocks the broker's reply until `RespondPermission(request_id, behavior,
updated_input_json, message)` arrives on `/org/famulus/Agent1`, then emits
`PermissionResolved(request_id, behavior)`. The broker's MCP wire shape is
specified (and verified against the real CLI) in C6.

- `behavior` MUST be `"allow"` or `"deny"`.
- `"allow"` maps to the documented permission-prompt-tool JSON reply
  `{"behavior":"allow","updatedInput":{...}}`. `updated_input_json` is `""` to
  keep the original tool input, or a JSON object that replaces it; it is only
  meaningful with `"allow"`.
- `"deny"` maps to `{"behavior":"deny","message":"..."}`. `message` is a
  human-readable reason; it is only meaningful with `"deny"`.
- Unanswered requests MUST eventually time out as deny; implementations SHOULD
  use a 120 s timeout (implementation guidance, not a wire-level constant).
- `RespondPermission` for a `request_id` that was already settled MUST fail
  with `org.famulus.Agent1.Error.NotFound` (first answer wins).

### Authenticated approvals (v1.1)

Tier 1 means user-authenticated and tier 2 admin-authenticated (C5), so an
`"allow"` of a tier-1 or tier-2 request is not settled by the call alone:

- The daemon MUST authenticate the process that called `RespondPermission`
  with polkit before the `"allow"` counts. famulus-agentd checks the
  actions `org.famulus.agent.approve-tier1` and
  `org.famulus.agent.approve-tier2`; polkit's agent (GNOME Shell) asks for
  the password.
- `RespondPermission` returns before that authentication finishes, so a
  slow password entry cannot time the call out. A successful return means
  only that the answer was accepted, not that the request is allowed.
- The outcome arrives only as `PermissionResolved`. A failed or cancelled
  authentication, or one the daemon cannot run, settles the request as
  `"deny"`. Clients MUST rely on `PermissionResolved`, never on the return
  of `RespondPermission`.
- While the authentication runs, the request stays pending: a `"deny"` from
  any client still settles it (first answer wins), and another `"allow"`
  fails with `org.famulus.Agent1.Error.Failed`.
- For a tier-1 or tier-2 request `updated_input_json` MUST be `""`. The
  password authorizes the input the user was shown, so an approval cannot
  swap in another input. Any other value fails with
  `org.famulus.Agent1.Error.Failed`, and the request stays pending.
- A `"deny"` and an `"allow"` of a tier-0 request need no authentication and
  settle the request at once; `updated_input_json` keeps its v1 meaning
  there.

The daemon MAY refuse answers from processes that cannot speak for the
user with `org.famulus.Agent1.Error.Failed`; famulus-agentd refuses every
process started by the supervised CLI, so a tool call cannot approve its
own request.

### Late clients: PendingPermissions

`PermissionRequest` is a signal: a client that starts or subscribes after
it was emitted never sees it. Examples are the chat app opened from the
Shell panel's notification and the panel after a Shell restart. The
`PendingPermissions` property closes that gap:

- The daemon MUST add a request to `PendingPermissions` before it emits the
  request's `PermissionRequest`, and MUST remove it before it emits the
  request's `PermissionResolved`. Every change emits `PropertiesChanged`.
- A request whose authentication is still running is still pending and
  stays listed.
- `PendingPermissions` is never persisted: pending requests do not outlive
  the daemon, so after a daemon start the property is empty.
- `GetManagedObjects` on the ObjectManager delivers the property with the
  other properties of each conversation.
- A late client SHOULD subscribe to the signals first and then read the
  property, de-duplicating by `request_id`. It answers listed requests with
  `RespondPermission` exactly as if it had seen the signal.

The property is additive: a client written against contracts-v1 ignores
it.

## ResponseComplete payload

The `result_json` string of `ResponseComplete` MUST parse as JSON and validate
against [`response-complete.schema.json`](response-complete.schema.json).
Required fields: `session_id`, `total_cost_usd`, `is_error`, `num_turns`.
Optional fields: `duration_ms`, `duration_api_ms`, `usage`, `subtype`,
`terminal_reason` (the last two are open-set strings passed through from the
CLI `result` line). No other keys are permitted.

## Errors

Methods on both interfaces MUST fail only with these D-Bus error names:

- `org.famulus.Agent1.Error.Failed` — generic failure. Among others:
  malformed `behavior` or `updated_input_json`, a non-empty
  `updated_input_json` for a tier-1 or tier-2 request, a second `"allow"`
  while one is being authenticated, an answer from a process that cannot
  speak for the user.
- `org.famulus.Agent1.Error.Closed` — the conversation is already closed.
- `org.famulus.Agent1.Error.NotFound` — unknown or already settled
  `request_id` passed to `RespondPermission`.

## Changes

- **contracts-v1.1** (ADR-018 items 4 and 5): documents authenticated
  approvals of tier-1/2 requests and the refusal of `updated_input_json`
  for them; adds the `PendingPermissions` property to `Conversation1`.
  Additive: no existing member changed its signature.

## Stability

Frozen at tag contracts-v1.1 (first frozen at contracts-v1). Changes require an ADR, maintainer review, and a new frozen tag; already-frozen tags are never rewritten.
