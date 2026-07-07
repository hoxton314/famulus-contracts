#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reference mapper for contract C6 (Claude stream-json -> D-Bus signals).

EXECUTABLE SPECIFICATION, not runtime code: famulus-agentd MUST behave as if
it ran map_line() over every stdout NDJSON line of the claude CLI. The
normative mapping table lives in README.md next to this file.

Tier stub: real tiers come from C5 policy resolution, never from the stream.
For deterministic fixtures this mapper uses a FIXED TEST POLICY — tool names
containing "wallpaper" -> tier 0, "Bash" -> tier 2, everything else -> tier
2. This stub is NOT the C5 default policy.
"""
import json
import sys
from pathlib import Path


def canonical_json(obj):
    """Canonical JSON per the shared contract literals."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def tier_for_tool(tool_name):
    """Fixed test policy stub (see module docstring); real tiers come from C5."""
    return 0 if "wallpaper" in tool_name else 2


def new_state():
    """Per-conversation mapper state kept by the daemon."""
    return {"session_id": None, "tool_names": {}, "text_streamed": False}


def map_line(state, line_obj, turn_id):
    """Map one parsed stdout NDJSON line to a list of D-Bus signal emissions."""
    kind = line_obj.get("type")
    if kind == "system":
        if line_obj.get("subtype") == "init":  # none -- internal: store session info
            state["session_id"] = line_obj.get("session_id")
        return []
    if kind == "stream_event":
        event = line_obj.get("event") or {}
        delta = event.get("delta") or {}
        if event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
            state["text_streamed"] = True
            return [{"signal": "ResponseDelta", "args": {"turn_id": turn_id, "text_chunk": delta["text"]}}]
        return []  # all other stream events are ignored in v1
    if kind == "assistant":
        emissions = []
        content = (line_obj.get("message") or {}).get("content") or []
        for block in content:
            if block.get("type") == "tool_use":
                state["tool_names"][block["id"]] = block["name"]
                emissions.append({"signal": "ToolCall", "args": {
                    "turn_id": turn_id, "tool_name": block["name"],
                    "input_json": canonical_json(block.get("input", {})),
                    "tier": tier_for_tool(block["name"])}})
            elif block.get("type") == "text" and not state["text_streamed"]:
                # SHOULD-level fallback: text never streamed as partial deltas
                emissions.append({"signal": "ResponseDelta", "args": {"turn_id": turn_id, "text_chunk": block["text"]}})
        if any(block.get("type") == "text" for block in content):
            state["text_streamed"] = False  # deltas consumed by their full message
        return emissions
    if kind == "user":
        emissions = []
        content = (line_obj.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if block.get("type") != "tool_result":
                continue
            raw = block.get("content", "")  # string stays; list is canonicalized
            emissions.append({"signal": "ToolResult", "args": {
                "turn_id": turn_id,
                "tool_name": state["tool_names"].get(block.get("tool_use_id"), ""),
                "result_json": raw if isinstance(raw, str) else canonical_json(raw),
                "is_error": bool(block.get("is_error", False))}})
        return emissions
    if kind == "result":
        payload = {"session_id": line_obj.get("session_id") or state["session_id"],
                   "total_cost_usd": line_obj["total_cost_usd"],
                   "is_error": line_obj["is_error"], "num_turns": line_obj["num_turns"]}
        for key in ("duration_ms", "duration_api_ms", "usage"):
            if key in line_obj:
                payload[key] = line_obj[key]
        state["text_streamed"] = False  # turn boundary
        return [{"signal": "ResponseComplete", "args": {"turn_id": turn_id, "result_json": canonical_json(payload)}}]
    return []  # unrecognized top-level type: ignored in v1 (the daemon logs it)


def _usage():
    print("usage: map_events.py FIXTURE.ndjson [--turn-id T1]", file=sys.stderr)
    return 2


def main(argv):
    turn_id, fixture, i = "T1", None, 0
    while i < len(argv):
        if argv[i] == "--turn-id":
            if i + 1 >= len(argv):
                return _usage()
            turn_id, i = argv[i + 1], i + 2
        elif fixture is None:
            fixture, i = argv[i], i + 1
        else:
            return _usage()
    if fixture is None:
        return _usage()
    path = Path(fixture)
    if not path.is_file():  # also try relative to this script so any CWD works
        path = Path(__file__).resolve().parent / fixture
    if not path.is_file():
        print("error: fixture not found: %s" % fixture, file=sys.stderr)
        return 2
    state, emissions = new_state(), []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            print("error: %s:%d: invalid JSON: %s" % (path.name, lineno, exc), file=sys.stderr)
            return 1
        emissions.extend(map_line(state, obj, turn_id))
    print(json.dumps(emissions, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
