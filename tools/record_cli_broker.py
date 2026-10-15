#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Stub approval broker used by record_cli.py (stdio MCP server, stdlib only).

Exposes one tool, `approve`, for `--permission-prompt-tool
mcp__famulus_broker__approve`. Every JSON-RPC message in either direction is
appended to $BROKER_LOG as {"dir": "in"|"out", "msg": ...}. The decision is
read from the JSON file $BROKER_DECISION ({"behavior": "allow"|"deny", ...});
an `allow` without `updatedInput` echoes the original input back.
"""
import json
import os
import sys

LOG = os.environ["BROKER_LOG"]
DECISION = os.environ.get("BROKER_DECISION", "")


def log(direction, msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"dir": direction, "msg": msg}) + "\n")


def send(msg):
    log("out", msg)
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def decide(arguments):
    decision = {"behavior": "allow"}
    if DECISION and os.path.exists(DECISION):
        with open(DECISION, encoding="utf-8") as f:
            decision = json.load(f)
    if decision.get("behavior") == "allow" and "updatedInput" not in decision:
        decision["updatedInput"] = arguments.get("input", {})
    return decision


for line in sys.stdin:
    if not line.strip():
        continue
    msg = json.loads(line)
    log("in", msg)
    mid, method = msg.get("id"), msg.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": msg["params"].get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "famulus_broker", "version": "0.0.0-recorder"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [{
            "name": "approve",
            "description": "Famulus permission broker (recording stub)",
            "inputSchema": {"type": "object", "additionalProperties": True}}]}})
    elif method == "tools/call":
        decision = decide(msg["params"].get("arguments", {}))
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text", "text": json.dumps(decision)}]}})
    elif mid is not None:
        send({"jsonrpc": "2.0", "id": mid, "result": {}})
