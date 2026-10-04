#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Contract C6 tests: fixtures parse, mapper output equals expected emissions,
fixture coverage matches the README mapping table, and ResponseComplete
payloads validate against the C2 schema when it exists.

Run from the repo root:
  .venv/bin/python -m unittest discover -s event-map -v
"""
import json
import unittest
from pathlib import Path

import map_events

HERE = Path(__file__).resolve().parent
FIXTURES_DIR = HERE / "fixtures"
EXPECTED_DIR = HERE / "expected"
RC_SCHEMA_PATH = HERE.parent / "dbus-agent" / "response-complete.schema.json"
RECORDED_DIR = HERE / "recorded" / "cli-2.1.284"
RECORDED_SCENES = ["text", "allow", "deny", "update", "interrupt"]
BROKER_SCENES = ["allow", "deny", "update"]

STDOUT_FIXTURES = [
    "01-init-and-text-turn.ndjson",
    "02-single-tool-turn.ndjson",
    "03-denied-tool-turn.ndjson",
    "04-error-result.ndjson",
    "05-parallel-tools-turn.ndjson",
]
INPUT_FIXTURE = "06-input-user-envelope.ndjson"
# Top-level "type" values covered by the README mapping table, per direction.
STDOUT_TYPES = {"system", "stream_event", "assistant", "user", "result"}
INPUT_TYPES = {"user", "control_request"}


def load_ndjson(path):
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            lines.append(json.loads(raw))
    return lines


class TestFixturesParse(unittest.TestCase):
    def test_fixture_files_present(self):
        names = sorted(p.name for p in FIXTURES_DIR.glob("*.ndjson"))
        self.assertEqual(names, sorted(STDOUT_FIXTURES + [INPUT_FIXTURE]))

    def test_every_line_is_json(self):
        for path in sorted(FIXTURES_DIR.glob("*.ndjson")):
            for lineno, raw in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1):
                if not raw.strip():
                    continue
                with self.subTest(fixture=path.name, line=lineno):
                    json.loads(raw)


class TestMapperMatchesExpected(unittest.TestCase):
    def test_output_equals_expected(self):
        for name in STDOUT_FIXTURES:
            with self.subTest(fixture=name):
                expected_path = EXPECTED_DIR / (Path(name).stem + ".json")
                self.assertTrue(expected_path.is_file(),
                                "missing expected file: %s" % expected_path.name)
                expected = json.loads(expected_path.read_text(encoding="utf-8"))
                state = map_events.new_state()
                emissions = []
                for obj in load_ndjson(FIXTURES_DIR / name):
                    emissions.extend(map_events.map_line(state, obj, "T1"))
                # byte-for-byte after a json round-trip
                self.assertEqual(
                    json.dumps(emissions, sort_keys=True, ensure_ascii=False),
                    json.dumps(expected, sort_keys=True, ensure_ascii=False))


class TestFixtureCoverage(unittest.TestCase):
    def test_stdout_fixture_types_covered_by_table(self):
        for name in STDOUT_FIXTURES:
            for i, obj in enumerate(load_ndjson(FIXTURES_DIR / name), 1):
                with self.subTest(fixture=name, line=i):
                    self.assertIn(obj.get("type"), STDOUT_TYPES)

    def test_input_fixture_matches_inferred_shapes(self):
        lines = load_ndjson(FIXTURES_DIR / INPUT_FIXTURE)
        self.assertEqual(len(lines), 2)
        for obj in lines:
            self.assertIn(obj.get("type"), INPUT_TYPES)
        user, interrupt = lines
        self.assertEqual(user["type"], "user")
        self.assertEqual(user["message"]["role"], "user")
        self.assertIsInstance(user["message"]["content"], str)
        self.assertGreater(len(user["message"]["content"]), 0)
        self.assertEqual(interrupt["type"], "control_request")
        self.assertIsInstance(interrupt["request_id"], str)
        self.assertGreater(len(interrupt["request_id"]), 0)
        self.assertEqual(interrupt["request"]["subtype"], "interrupt")


class TestResponseCompleteSchema(unittest.TestCase):
    @unittest.skipUnless(RC_SCHEMA_PATH.is_file(),
                         "C2 response-complete.schema.json not present yet")
    def test_expected_response_complete_payloads_validate(self):
        import jsonschema
        schema = json.loads(RC_SCHEMA_PATH.read_text(encoding="utf-8"))
        paths = sorted(EXPECTED_DIR.glob("*.json")) + sorted((RECORDED_DIR / "expected").glob("*.json"))
        for path in paths:
            for emission in json.loads(path.read_text(encoding="utf-8")):
                if emission["signal"] != "ResponseComplete":
                    continue
                with self.subTest(expected=path.name):
                    payload = json.loads(emission["args"]["result_json"])
                    jsonschema.validate(payload, schema)


class TestRecordedCli(unittest.TestCase):
    """Sanitized recordings of the real claude CLI (see recorded/README.md)."""

    def test_mapper_matches_recorded_expected(self):
        for scene in RECORDED_SCENES:
            with self.subTest(scene=scene):
                state, emissions = map_events.new_state(), []
                for obj in load_ndjson(RECORDED_DIR / (scene + ".stdout.ndjson")):
                    emissions.extend(map_events.map_line(state, obj, "T1"))
                expected = json.loads((RECORDED_DIR / "expected" / (scene + ".json")).read_text(encoding="utf-8"))
                self.assertEqual(emissions, expected)

    def test_tool_ids_correlate(self):
        for scene in BROKER_SCENES:
            with self.subTest(scene=scene):
                emissions = json.loads((RECORDED_DIR / "expected" / (scene + ".json")).read_text(encoding="utf-8"))
                calls = {e["args"]["tool_use_id"] for e in emissions if e["signal"] == "ToolCall"}
                results = {e["args"]["tool_use_id"] for e in emissions if e["signal"] == "ToolResult"}
                self.assertTrue(calls)
                self.assertEqual(calls, results)

    def test_stdin_envelopes_match_table(self):
        for scene in RECORDED_SCENES:
            for obj in load_ndjson(RECORDED_DIR / (scene + ".stdin.ndjson")):
                with self.subTest(scene=scene):
                    self.assertIn(obj["type"], INPUT_TYPES)
                    if obj["type"] == "user":
                        self.assertEqual(obj["message"]["role"], "user")
                    else:
                        self.assertEqual(obj["request"]["subtype"], "interrupt")

    def test_interrupt_yields_error_result_and_survives(self):
        results = [o for o in load_ndjson(RECORDED_DIR / "interrupt.stdout.ndjson") if o["type"] == "result"]
        self.assertEqual([r["is_error"] for r in results], [True, False])
        acks = [o for o in load_ndjson(RECORDED_DIR / "interrupt.stdout.ndjson") if o["type"] == "control_response"]
        sent = [o for o in load_ndjson(RECORDED_DIR / "interrupt.stdin.ndjson") if o["type"] == "control_request"]
        self.assertEqual(acks[0]["response"]["request_id"], sent[0]["request_id"])

    def test_broker_wire_shape(self):
        for scene in BROKER_SCENES:
            msgs = [m["msg"] for m in load_ndjson(RECORDED_DIR / (scene + ".broker.ndjson"))]
            call = next(m for m in msgs if m.get("method") == "tools/call")
            reply = next(m for m in msgs if m.get("id") == call["id"] and "result" in m)
            with self.subTest(scene=scene):
                self.assertEqual(call["params"]["name"], "approve")
                self.assertEqual(set(call["params"]["arguments"]), {"tool_name", "input", "tool_use_id"})
                decision = json.loads(reply["result"]["content"][0]["text"])
                self.assertIn(decision["behavior"], ("allow", "deny"))


if __name__ == "__main__":
    unittest.main()
