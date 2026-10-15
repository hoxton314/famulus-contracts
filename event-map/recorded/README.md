# C6 recorded fixtures (real CLI)

Each `cli-<version>/` directory holds **sanitized recordings of the real,
unmodified `claude` CLI** driven exactly as famulus-agentd drives it:

```
claude -p --input-format stream-json --output-format stream-json --verbose \
  --include-partial-messages --permission-prompt-tool mcp__famulus_broker__approve \
  --mcp-config <broker.json> --strict-mcp-config --setting-sources project \
  --permission-mode default --model haiku --tools Bash,Read
```

with a stub stdio MCP server standing in for the approval broker.
`tools/record_cli.py` does all of this and writes `cli-<version>/`; it
uses haiku and costs a few cents.

| Version | Recorded | Notes |
|---------|----------|-------|
| `cli-2.1.284` | 2026-10-04 | basis of contracts-v1 |
| `cli-2.1.296` | 2026-10-15 | no new stdout types; broker request/reply shape unchanged |

| Scene | What it proves |
|-------|----------------|
| `text` | two sequential user turns in one long-lived process; `system/init` repeats per turn |
| `allow` | Bash call gated by the broker; `{"behavior":"allow","updatedInput":<original>}` runs it |
| `deny` | `{"behavior":"deny","message":...}` → `tool_result` `is_error: true` with that message; `result.permission_denials` |
| `update` | `allow` with a rewritten `updatedInput.command` → the rewritten command is what runs |
| `interrupt` | stdin `control_request` interrupt mid-stream → `control_response` ack + `result` `is_error: true`; next turn in the same process succeeds |

Per scene: `<scene>.stdout.ndjson` (CLI → daemon), `<scene>.stdin.ndjson`
(daemon → CLI), `<scene>.broker.ndjson` (MCP `initialize`/`tools/call` and the
broker's replies, gated scenes only), and `expected/<scene>.json` (output of
`../map_events.py` with `--turn-id T1`; multi-turn scenes reuse `T1` for every
turn because the reference mapper has no turn splitting).

**Sanitization** (stdout content is otherwise byte-for-byte what the CLI
emitted, re-serialized compactly): host paths rewritten to
`/home/user/.local/share/famulus/conversations/0192f3a0c1d27e4fb6a8`; the
recording host's own `plugins`, `skills`, `slash_commands`,
`terminal_slash_commands`, `agents`, `memory_paths` emptied in
`system/init`; `rate_limit_event` utilization zeroed.

To add a version:

```sh
tools/record_cli.py                       # writes event-map/recorded/cli-<version>/
for s in text allow deny update interrupt; do
  mkdir -p event-map/recorded/cli-<version>/expected
  .venv/bin/python event-map/map_events.py event-map/recorded/cli-<version>/$s.stdout.ndjson \
    --turn-id T1 > event-map/recorded/cli-<version>/expected/$s.json
done
just validate                             # tests cover every cli-* directory
```

Adding a recording changes no contract shape, so it ships as a
fixtures-only patch tag (`contracts-v1.0.<n>`). A diff in expected emissions between versions is a
contract-relevant CLI change and needs review.
