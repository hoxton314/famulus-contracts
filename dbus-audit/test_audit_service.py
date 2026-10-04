#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Contract lock tests for C7 (dbus-audit, org.famulus.Audit1).

Run from the repository root:
  .venv/bin/python -m unittest discover -s dbus-audit -v
"""

import json
import shutil
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import jsonschema

HERE = Path(__file__).resolve().parent
XML_PATH = HERE / "org.famulus.Audit1.xml"
SCHEMA_PATH = HERE / "append-request.schema.json"
C1_SCHEMA_PATH = HERE.parent / "audit-log" / "audit-record.schema.json"
VALIDATOR_PATH = HERE / "validate_append_request.py"
FIXTURES = HERE / "fixtures"
WRITER_ASSIGNED = {"ts", "prev_hash", "hash"}
GDBUS_CODEGEN = shutil.which("gdbus-codegen")

DOCTYPE_PREFIX = (
    '<!DOCTYPE node PUBLIC '
    '"-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"'
)

# (arg name, D-Bus type, direction) per method, in declaration order.
EXPECTED_METHODS = {
    "Append": [
        ("record_json", "s", "in"),
        ("ts", "s", "out"),
        ("hash", "s", "out"),
    ],
    "Query": [
        ("conversation_id", "s", "in"),
        ("after_event_id", "s", "in"),
        ("limit", "u", "in"),
        ("records_ndjson", "s", "out"),
        ("more", "b", "out"),
    ],
    "Verify": [
        ("ok", "b", "out"),
        ("record_count", "u", "out"),
        ("head_hash", "s", "out"),
        ("message", "s", "out"),
    ],
}


def run_validator(*args):
    return subprocess.run([sys.executable, str(VALIDATOR_PATH), *args],
                          capture_output=True, text=True)


class TestIntrospectionXml(unittest.TestCase):
    def test_doctype(self):
        self.assertTrue(XML_PATH.read_text(encoding="utf-8").startswith(DOCTYPE_PREFIX))

    def test_complete_shape(self):
        ifaces = ET.parse(XML_PATH).getroot().findall("interface")
        self.assertEqual(len(ifaces), 1)
        iface = ifaces[0]
        self.assertEqual(iface.get("name"), "org.famulus.Audit1")
        methods = {m.get("name"): [(a.get("name"), a.get("type"), a.get("direction"))
                                   for a in m.findall("arg")]
                   for m in iface.findall("method")}
        self.assertEqual(methods, EXPECTED_METHODS)
        # No signals (cross-user leak) and no properties, by design.
        self.assertEqual(iface.findall("signal"), [])
        self.assertEqual(iface.findall("property"), [])

    @unittest.skipUnless(GDBUS_CODEGEN, "gdbus-codegen not installed")
    def test_gdbus_codegen(self):
        proc = subprocess.run([GDBUS_CODEGEN, "--interface-info-body",
                               "--output", "/dev/null", str(XML_PATH)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class TestSchemaMatchesC1(unittest.TestCase):
    """The append request is exactly C1 minus the writer-assigned members."""

    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.c1 = json.loads(C1_SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_valid_draft_2020_12(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_properties_identical_to_c1(self):
        expected = {k: v for k, v in self.c1["properties"].items() if k not in WRITER_ASSIGNED}
        self.assertEqual(self.schema["properties"], expected)

    def test_required_identical_to_c1(self):
        expected = [k for k in self.c1["required"] if k not in WRITER_ASSIGNED]
        self.assertEqual(self.schema["required"], expected)

    def test_closed_object(self):
        self.assertIs(self.schema["additionalProperties"], False)

    def test_writer_output_is_valid_c1(self):
        payload = json.loads((FIXTURES / "valid-tier0.json").read_text(encoding="utf-8"))
        payload.update({"ts": "2026-10-04T12:00:00.000Z", "prev_hash": "0" * 64, "hash": "a" * 64})
        jsonschema.Draft202012Validator(self.c1).validate(payload)


class TestValidatorCli(unittest.TestCase):
    def test_valid_fixtures(self):
        proc = run_validator(str(FIXTURES / "valid-tier0.json"),
                             str(FIXTURES / "valid-tier2-snapshot.json"))
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_invalid_fixtures(self):
        for name in ("invalid-has-hash.json", "invalid-float.json"):
            with self.subTest(fixture=name):
                self.assertEqual(run_validator(str(FIXTURES / name)).returncode, 1)

    def test_usage_error(self):
        self.assertEqual(run_validator().returncode, 2)
        self.assertEqual(run_validator(str(FIXTURES / "missing.json")).returncode, 2)


if __name__ == "__main__":
    unittest.main()
