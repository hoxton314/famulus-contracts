# C6 fixtures

**All fixtures are SYNTHETIC**: hand-written to match the documented
stream-json shapes (see `../README.md`, "Verification status"), not recorded
from a live `claude` CLI. Each file is a complete, self-consistent scene
with one `session_id`, plausible `toolu_*`/`msg_*` ids, and model
`claude-sonnet-4-6`.

Files `01`–`05` are the **stdout** direction (CLI → daemon); each has a
matching `../expected/<basename>.json` listing the exact ordered D-Bus
signal emissions. File `06` is the **stdin** direction (daemon → CLI) and was
originally **INFERRED** — the user-turn and interrupt envelopes come from Agent SDK
analogy (Anthropic issue #24594), not from CLI documentation, and have no
expected-emissions file. Both envelopes have since been VERIFIED against
CLI 2.1.284 (see `../recorded/`).

| File | Scene |
|------|-------|
| `01-init-and-text-turn.ndjson` | init, full partial-message stream (message_start → 3 text deltas → message_stop), assistant full text, success result |
| `02-single-tool-turn.ndjson` | init, one `mcp__famulus_desktop__wallpaper_set` tool_use, tool_result, streamed text deltas, assistant text, success result |
| `03-denied-tool-turn.ndjson` | `Bash` tool_use, tool_result `is_error: true` ("Permission denied by user"), assistant apology, success result (`is_error: false` — the turn succeeded even though the tool was denied) |
| `04-error-result.ndjson` | init, then a `result` with subtype `error_during_execution` and `is_error: true`, no assistant content |
| `05-parallel-tools-turn.ndjson` | one assistant message with TWO tool_use blocks, two tool_result envelopes (one list-content, one string-content), assistant text, success result |
| `06-input-user-envelope.ndjson` | stdin direction (verified 2.1.284): one user-turn envelope and one `control_request` interrupt envelope |
