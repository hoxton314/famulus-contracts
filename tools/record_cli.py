#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Record the C6 scenes against the installed `claude` CLI.

Usage:
  tools/record_cli.py [--claude PATH] [--model haiku] [--out event-map/recorded]

Drives the real, unmodified CLI exactly as famulus-agentd does (persistent
stream-json, --permission-prompt-tool mcp__famulus_broker__approve) with
tools/record_cli_broker.py standing in for the approval broker, and writes
sanitized scenes to <out>/cli-<version>/ (see event-map/recorded/README.md).
Then run event-map/map_events.py over them to create expected/ and review the
diff against earlier versions.

This spends real API usage (a few cents with haiku). Stdlib only.
"""
import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
BROKER = HERE / "record_cli_broker.py"
CONV_DIR = "/home/user/.local/share/famulus/conversations/0192f3a0c1d27e4fb6a8"
PROJECT_DIR = "/home/user/.claude/projects/-home-user-.local-share-famulus-conversations-0192f3a0c1d27e4fb6a8"
# init fields that enumerate the recording host's own setup — emptied.
HOST_LISTS = ("plugins", "skills", "slash_commands", "terminal_slash_commands", "agents", "memory_paths")
SCENES = ("text", "allow", "deny", "update", "interrupt")


class Scene:
    """One CLI process plus its stub broker, recording all three channels."""

    def __init__(self, claude, model, workdir, name):
        self.name = name
        self.cwd = workdir / "cwd" / name
        self.cwd.mkdir(parents=True)
        self.raw = workdir / "raw"
        self.raw.mkdir(exist_ok=True)
        self.decision = self.raw / f"{name}.decision.json"
        mcp = {"mcpServers": {"famulus_broker": {
            "type": "stdio", "command": sys.executable, "args": [str(BROKER)],
            "env": {"BROKER_LOG": str(self.raw / f"{name}.broker.log"),
                    "BROKER_DECISION": str(self.decision)}}}}
        mcp_path = self.raw / f"{name}.mcp.json"
        mcp_path.write_text(json.dumps(mcp), encoding="utf-8")
        cmd = [claude, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
               "--verbose", "--include-partial-messages",
               "--permission-prompt-tool", "mcp__famulus_broker__approve",
               "--mcp-config", str(mcp_path), "--strict-mcp-config",
               "--setting-sources", "project", "--permission-mode", "default",
               "--model", model, "--tools", "Bash,Read"]
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
        self.proc = subprocess.Popen(cmd, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, env=env, bufsize=1)
        self.stdout = open(self.raw / f"{name}.stdout.ndjson", "w", encoding="utf-8")
        self.stdin = open(self.raw / f"{name}.stdin.ndjson", "w", encoding="utf-8")
        self.events = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            self.stdout.write(line)
            self.stdout.flush()
            try:
                self.events.put(json.loads(line))
            except json.JSONDecodeError:
                pass
        self.events.put(None)

    def write(self, obj):
        line = json.dumps(obj)
        self.stdin.write(line + "\n")
        self.stdin.flush()
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def user(self, text):
        self.write({"type": "user", "message": {"role": "user", "content": text}})

    def set_decision(self, decision):
        self.decision.write_text(json.dumps(decision), encoding="utf-8")

    def wait_result(self, on_event=None, timeout=180):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                ev = self.events.get(timeout=1)
            except queue.Empty:
                continue
            if ev is None:
                raise RuntimeError(f"{self.name}: CLI exited before the result")
            if on_event:
                on_event(ev)
            if ev.get("type") == "result":
                return ev
        raise RuntimeError(f"{self.name}: timed out waiting for a result")

    def close(self):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        time.sleep(0.3)
        self.stdout.close()
        self.stdin.close()


def run_scene(scene):
    """Drive one scene; returns a dict of checks for the summary."""
    s = scene
    if s.name == "text":
        s.user("Reply with exactly: alpha")
        s.wait_result()
        s.user("Reply with exactly: beta")
        return {"result": s.wait_result()["result"]}
    if s.name == "allow":
        s.set_decision({"behavior": "allow"})
        s.user("Use the Bash tool to run exactly this command: echo famulus-allow > allow.txt . Then say done.")
        s.wait_result()
        return {"file": (s.cwd / "allow.txt").read_text().strip() if (s.cwd / "allow.txt").exists() else None}
    if s.name == "deny":
        s.set_decision({"behavior": "deny", "message": "Denied by Famulus recorder"})
        s.user("Use the Bash tool to run exactly: echo famulus-deny > deny.txt . If denied, say 'was denied' and stop.")
        r = s.wait_result()
        return {"file_exists": (s.cwd / "deny.txt").exists(), "denials": len(r.get("permission_denials", []))}
    if s.name == "update":
        s.set_decision({"behavior": "allow",
                        "updatedInput": {"command": "echo famulus-rewritten > upd.txt",
                                         "description": "rewritten by broker"}})
        s.user("Use the Bash tool to run exactly: echo original > upd.txt . Then say done.")
        s.wait_result()
        return {"file": (s.cwd / "upd.txt").read_text().strip() if (s.cwd / "upd.txt").exists() else None}
    if s.name == "interrupt":
        s.user("Count slowly from 1 to 300, one number per line, no tools.")
        seen = {"n": 0}

        def interrupt_after_deltas(ev):
            if ev.get("type") == "stream_event":
                seen["n"] += 1
                if seen["n"] == 15:
                    s.write({"type": "control_request", "request_id": str(uuid.uuid4()),
                             "request": {"subtype": "interrupt"}})
        first = s.wait_result(on_event=interrupt_after_deltas)
        s.user("Reply with exactly: after-interrupt")
        second = s.wait_result()
        return {"interrupted_is_error": first["is_error"], "after": second["result"]}
    raise ValueError(s.name)


def scrub_str(s, workdir, home):
    s = re.sub(re.escape(str(workdir)) + r"/cwd/[a-z]+", CONV_DIR, s)
    s = re.sub(re.escape(home) + r"/\.claude/projects/[^\"\s/]+", PROJECT_DIR, s)
    s = s.replace(str(workdir), "/tmp/famulus-recording")
    return s.replace(home, "/home/user")


def scrub(o, workdir, home):
    if isinstance(o, dict):
        return {k: scrub(v, workdir, home) for k, v in o.items()}
    if isinstance(o, list):
        return [scrub(v, workdir, home) for v in o]
    if isinstance(o, str):
        return scrub_str(o, workdir, home)
    return o


def sanitize_line(obj, workdir, home):
    obj = scrub(obj, workdir, home)
    if obj.get("type") == "system" and obj.get("subtype") == "init":
        for key in HOST_LISTS:
            if key in obj:
                obj[key] = [] if isinstance(obj[key], list) else {}
        if "messaging_socket_path" in obj:
            obj["messaging_socket_path"] = "/run/user/1000/claude/messaging.sock"
    if obj.get("type") == "rate_limit_event":
        for window in (obj.get("rate_limit_info", {}).get("unifiedWindows") or {}).values():
            window["utilization"] = 0.0
    return obj


def write_ndjson(path, objs):
    with open(path, "w", encoding="utf-8") as f:
        for o in objs:
            f.write(json.dumps(o, ensure_ascii=False, separators=(",", ":")) + "\n")


def export(workdir, out, name):
    home = os.path.expanduser("~")
    raw = workdir / "raw"
    for suffix in ("stdout.ndjson", "stdin.ndjson"):
        lines = [json.loads(l) for l in (raw / f"{name}.{suffix}").read_text(encoding="utf-8").splitlines() if l.strip()]
        write_ndjson(out / f"{name}.{suffix}", [sanitize_line(o, workdir, home) for o in lines])
    log = raw / f"{name}.broker.log"
    if not log.exists():
        return
    msgs = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    keep = [m for m in msgs if m["msg"].get("method") in ("initialize", "tools/call")
            or (m["dir"] == "out" and "content" in m["msg"].get("result", {}))]
    if any(m["msg"].get("method") == "tools/call" for m in keep):
        write_ndjson(out / f"{name}.broker.ndjson", [scrub(m, workdir, home) for m in keep])


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claude", default="claude")
    parser.add_argument("--model", default="haiku")
    parser.add_argument("--out", default=str(HERE.parent / "event-map" / "recorded"))
    args = parser.parse_args(argv)

    version = subprocess.run([args.claude, "--version"], capture_output=True, text=True, check=True).stdout.split()[0]
    out = Path(args.out) / f"cli-{version}"
    if out.exists():
        print(f"error: {out} already exists", file=sys.stderr)
        return 2
    workdir = Path(tempfile.mkdtemp(prefix="famulus-record-"))
    summary = {"version": version}
    try:
        for name in SCENES:
            scene = Scene(args.claude, args.model, workdir, name)
            try:
                summary[name] = run_scene(scene)
            finally:
                scene.close()
        out.mkdir(parents=True)
        for name in SCENES:
            export(workdir, out, name)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
