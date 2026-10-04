#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Structural-lock tests for contract C2 (org.famulus.Agent1 / org.famulus.Conversation1).

Run from the repo root:
  .venv/bin/python -m unittest discover -s dbus-agent -v
"""

import json
import shutil
import subprocess
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import jsonschema

HERE = Path(__file__).resolve().parent
AGENT_XML = HERE / "org.famulus.Agent1.xml"
CONVERSATION_XML = HERE / "org.famulus.Conversation1.xml"
SCHEMA_PATH = HERE / "response-complete.schema.json"
GDBUS_CODEGEN = shutil.which("gdbus-codegen")

DOCTYPE_PREFIX = (
    '<!DOCTYPE node PUBLIC '
    '"-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"'
)

# Complete expected shape of both interfaces. Any drift fails the tests.
# methods: name -> ordered list of (arg_name, dbus_type, direction)
# signals: name -> ordered list of (arg_name, dbus_type)
# properties: name -> (dbus_type, access)
EXPECTED_AGENT1 = {
    "methods": {
        "CreateConversation": [
            ("conversation_path", "o", "out"),
        ],
        "RespondPermission": [
            ("request_id", "s", "in"),
            ("behavior", "s", "in"),
            ("updated_input_json", "s", "in"),
            ("message", "s", "in"),
        ],
    },
    "signals": {},
    "properties": {
        "DaemonVersion": ("s", "read"),
        "CliVersion": ("s", "read"),
        "AuthMethod": ("s", "read"),
    },
}

EXPECTED_CONVERSATION1 = {
    "methods": {
        "SendMessage": [
            ("text", "s", "in"),
            ("turn_id", "s", "out"),
        ],
        "Cancel": [],
        "GetTranscript": [
            ("transcript_json", "s", "out"),
        ],
        "Close": [],
    },
    "signals": {
        "ResponseDelta": [
            ("turn_id", "s"),
            ("text_chunk", "s"),
        ],
        "ToolCall": [
            ("turn_id", "s"),
            ("tool_use_id", "s"),
            ("tool_name", "s"),
            ("input_json", "s"),
            ("tier", "u"),
        ],
        "ToolResult": [
            ("turn_id", "s"),
            ("tool_use_id", "s"),
            ("tool_name", "s"),
            ("result_json", "s"),
            ("is_error", "b"),
        ],
        "PermissionRequest": [
            ("request_id", "s"),
            ("turn_id", "s"),
            ("tool_use_id", "s"),
            ("tool_name", "s"),
            ("input_json", "s"),
            ("tier", "u"),
        ],
        "PermissionResolved": [
            ("request_id", "s"),
            ("behavior", "s"),
        ],
        "ResponseComplete": [
            ("turn_id", "s"),
            ("result_json", "s"),
        ],
        "ConversationError": [
            ("message", "s"),
        ],
    },
    "properties": {
        "Id": ("s", "read"),
        "SessionId": ("s", "read"),
        "Busy": ("b", "read"),
    },
}


def interface_shape(iface):
    """Extract the complete structural shape of an <interface> element."""
    methods = {}
    for method in iface.findall("method"):
        methods[method.get("name")] = [
            (arg.get("name"), arg.get("type"), arg.get("direction"))
            for arg in method.findall("arg")
        ]
    signals = {}
    for signal in iface.findall("signal"):
        signals[signal.get("name")] = [
            (arg.get("name"), arg.get("type"))
            for arg in signal.findall("arg")
        ]
    properties = {
        prop.get("name"): (prop.get("type"), prop.get("access"))
        for prop in iface.findall("property")
    }
    return {"methods": methods, "signals": signals, "properties": properties}


def single_interface(path):
    """Parse the XML file and return its single <interface> element."""
    root = ET.parse(path).getroot()
    interfaces = root.findall("interface")
    if len(interfaces) != 1:
        raise AssertionError(
            f"{path.name}: expected exactly 1 interface, found {len(interfaces)}"
        )
    return interfaces[0]


class DoctypeTest(unittest.TestCase):
    def test_agent1_starts_with_freedesktop_doctype(self):
        text = AGENT_XML.read_text(encoding="utf-8")
        self.assertTrue(
            text.startswith(DOCTYPE_PREFIX),
            f"{AGENT_XML.name} must start with the freedesktop introspection DOCTYPE",
        )

    def test_conversation1_starts_with_freedesktop_doctype(self):
        text = CONVERSATION_XML.read_text(encoding="utf-8")
        self.assertTrue(
            text.startswith(DOCTYPE_PREFIX),
            f"{CONVERSATION_XML.name} must start with the freedesktop introspection DOCTYPE",
        )


class StructuralLockTest(unittest.TestCase):
    def test_agent1_parses(self):
        ET.parse(AGENT_XML)

    def test_conversation1_parses(self):
        ET.parse(CONVERSATION_XML)

    def test_agent1_interface_name(self):
        iface = single_interface(AGENT_XML)
        self.assertEqual(iface.get("name"), "org.famulus.Agent1")

    def test_conversation1_interface_name(self):
        iface = single_interface(CONVERSATION_XML)
        self.assertEqual(iface.get("name"), "org.famulus.Conversation1")

    def test_agent1_complete_shape(self):
        shape = interface_shape(single_interface(AGENT_XML))
        self.assertEqual(shape, EXPECTED_AGENT1)

    def test_conversation1_complete_shape(self):
        shape = interface_shape(single_interface(CONVERSATION_XML))
        self.assertEqual(shape, EXPECTED_CONVERSATION1)


class GDBusCodegenTest(unittest.TestCase):
    @unittest.skipUnless(GDBUS_CODEGEN, "gdbus-codegen not installed")
    def test_agent1_passes_gdbus_codegen(self):
        proc = subprocess.run(
            [GDBUS_CODEGEN, "--interface-info-body",
             "--output", "/dev/null", str(AGENT_XML)],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    @unittest.skipUnless(GDBUS_CODEGEN, "gdbus-codegen not installed")
    def test_conversation1_passes_gdbus_codegen(self):
        proc = subprocess.run(
            [GDBUS_CODEGEN, "--interface-info-body",
             "--output", "/dev/null", str(CONVERSATION_XML)],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


class ResponseCompleteSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.validator = jsonschema.Draft202012Validator(cls.schema)

    @staticmethod
    def valid_payload():
        return {
            "session_id": "6f2c1a4e-example-session",
            "total_cost_usd": 0.0421,
            "is_error": False,
            "num_turns": 3,
            "duration_ms": 15234,
            "duration_api_ms": 9120,
            "usage": {"input_tokens": 812, "output_tokens": 344},
            "subtype": "success",
            "terminal_reason": "completed",
        }

    def test_schema_is_valid_draft_2020_12(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)

    def test_valid_payload_validates(self):
        self.validator.validate(self.valid_payload())

    def test_minimal_payload_validates(self):
        self.validator.validate({
            "session_id": "s",
            "total_cost_usd": 0,
            "is_error": True,
            "num_turns": 1,
        })

    def test_missing_session_id_fails(self):
        payload = self.valid_payload()
        del payload["session_id"]
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(payload)

    def test_extra_key_fails(self):
        payload = self.valid_payload()
        payload["unexpected_key"] = "nope"
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(payload)


if __name__ == "__main__":
    unittest.main()
