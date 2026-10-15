#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Contract lock tests for C4 (dbus-snapshot).

Run from the repository root:
  .venv/bin/python -m unittest discover -s dbus-snapshot -v
"""

import json
import os
import re
import shutil
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import jsonschema

HERE = Path(__file__).resolve().parent
XML_PATH = HERE / "org.famulus.Snapshot1.xml"
SCHEMA_PATH = HERE / "snapshot-ref.schema.json"
VALIDATOR_PATH = HERE / "validate_snapshot_contract.py"
README_PATH = HERE / "README.md"

# Every D-Bus error C4 names (v1.1 added NotAuthorized and Failed).
EXPECTED_ERRORS = [
    "UnknownSubvolume", "InvalidTag", "NotFound", "Busy",
    "NotAuthorized", "Failed",
]
# REQUIRED List keys and their variant types (v1.1 added excluded).
EXPECTED_LIST_KEYS = {
    "snapshot_ref": "s",
    "event_id": "s",
    "subvolumes": "as",
    "tag": "s",
    "created_unix": "t",
    "deployment_digest": "s",
    "excluded": "a{sas}",
}

DOCTYPE_PREFIX = (
    '<!DOCTYPE node PUBLIC '
    '"-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"'
)

GDBUS_CODEGEN = shutil.which("gdbus-codegen")

# (arg name, D-Bus type, direction) per method, in declaration order.
EXPECTED_METHODS = {
    "Create": [
        ("subvolumes", "as", "in"),
        ("tag", "s", "in"),
        ("snapshot_ref", "s", "out"),
    ],
    "Restore": [
        ("snapshot_ref", "s", "in"),
        ("success", "b", "out"),
    ],
    "List": [
        ("snapshots", "aa{sv}", "out"),
    ],
    "Prune": [
        ("keep_last", "u", "in"),
        ("pruned_count", "u", "out"),
    ],
}

VALID_REFS = [
    "famulus-snap/019811a2-7c3e-7d10-9b8a-3f2e1d0c4b5a/etc+var@1751884800",
    "famulus-snap/019811a2-7c3e-7d10-9b8a-3f2e1d0c4b5a/etc@1751884800",
]

INVALID_REFS = {
    "missing famulus-snap prefix":
        "019811a2-7c3e-7d10-9b8a-3f2e1d0c4b5a/etc+var@1751884800",
    "uppercase UUID":
        "famulus-snap/019811A2-7C3E-7D10-9B8A-3F2E1D0C4B5A/etc+var@1751884800",
    "UUID version 4 (nibble not 7)":
        "famulus-snap/019811a2-7c3e-4d10-9b8a-3f2e1d0c4b5a/etc+var@1751884800",
    "empty subvols":
        "famulus-snap/019811a2-7c3e-7d10-9b8a-3f2e1d0c4b5a/@1751884800",
    "subvols with slash":
        "famulus-snap/019811a2-7c3e-7d10-9b8a-3f2e1d0c4b5a/etc/var@1751884800",
    "trailing plus":
        "famulus-snap/019811a2-7c3e-7d10-9b8a-3f2e1d0c4b5a/etc+@1751884800",
    "missing @ts":
        "famulus-snap/019811a2-7c3e-7d10-9b8a-3f2e1d0c4b5a/etc+var",
    "negative ts":
        "famulus-snap/019811a2-7c3e-7d10-9b8a-3f2e1d0c4b5a/etc+var@-1751884800",
}


class TestIntrospectionXml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = XML_PATH.read_text(encoding="utf-8")
        cls.root = ET.fromstring(cls.text)

    def test_starts_with_freedesktop_doctype(self):
        self.assertTrue(
            self.text.startswith(DOCTYPE_PREFIX),
            "org.famulus.Snapshot1.xml must begin with the freedesktop "
            "introspection DOCTYPE",
        )

    def test_root_is_node_with_single_interface(self):
        self.assertEqual(self.root.tag, "node")
        children = [c for c in self.root if c.tag != "annotation"]
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].tag, "interface")
        self.assertEqual(children[0].get("name"), "org.famulus.Snapshot1")

    def _interface(self):
        return self.root.find("interface")

    def test_no_signals_or_properties_or_extra_members(self):
        iface = self._interface()
        allowed = {"method", "annotation"}
        for child in iface:
            self.assertIn(
                child.tag, allowed,
                f"unexpected interface member <{child.tag}>",
            )

    def test_methods_exact_set(self):
        iface = self._interface()
        names = [m.get("name") for m in iface.findall("method")]
        self.assertEqual(len(names), len(set(names)), "duplicate method names")
        self.assertEqual(set(names), set(EXPECTED_METHODS))

    def test_method_args_names_types_directions(self):
        iface = self._interface()
        for method in iface.findall("method"):
            name = method.get("name")
            with self.subTest(method=name):
                for child in method:
                    self.assertIn(child.tag, {"arg", "annotation"})
                got = [
                    (a.get("name"), a.get("type"), a.get("direction"))
                    for a in method.findall("arg")
                ]
                self.assertEqual(got, EXPECTED_METHODS[name])

    @unittest.skipUnless(GDBUS_CODEGEN, "gdbus-codegen not installed")
    def test_gdbus_codegen_accepts_file(self):
        proc = subprocess.run(
            [GDBUS_CODEGEN, "--interface-info-body", "--output", os.devnull,
             str(XML_PATH)],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


class TestReadmeSpec(unittest.TestCase):
    """The normative tables in README.md name every error and List key."""

    @classmethod
    def setUpClass(cls):
        cls.readme = README_PATH.read_text(encoding="utf-8")
        cls.xml = XML_PATH.read_text(encoding="utf-8")

    def test_errors_table(self):
        rows = re.findall(r"^\| `org\.famulus\.Snapshot1\.Error\.(\w+)` \|",
                          self.readme, re.M)
        self.assertEqual(rows, EXPECTED_ERRORS)
        for name in ("NotAuthorized", "Failed"):
            self.assertIn(f"org.famulus.Snapshot1.Error.{name}", self.xml)

    def test_list_keys_table(self):
        section = self.readme.split("\n## List\n", 1)[1].split("\n## ", 1)[0]
        rows = dict(re.findall(r"^\| `(\w+)` \| `([^`]+)` \|", section, re.M))
        self.assertEqual(rows, EXPECTED_LIST_KEYS)
        self.assertIn("excluded (a{sas}", self.xml)

    def test_audit_log_never_restored(self):
        for path in ("/var/log/famulus/audit/", "/var/lib/famulus/audit/"):
            self.assertIn(path, self.readme)
        self.assertIn("The audit log MUST NOT be part of a snapshot set", self.readme)


class TestSnapshotRefSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.pattern = re.compile(cls.schema["pattern"])
        cls.validator = jsonschema.validators.Draft202012Validator(cls.schema)

    def test_schema_is_valid_draft_2020_12(self):
        jsonschema.validators.Draft202012Validator.check_schema(self.schema)
        self.assertEqual(
            self.schema["$schema"],
            "https://json-schema.org/draft/2020-12/schema",
        )
        self.assertEqual(
            self.schema["$id"],
            "https://famulus.dev/contracts/v1/snapshot-ref.schema.json",
        )
        self.assertEqual(self.schema["type"], "string")
        self.assertIn("description", self.schema)

    def test_pattern_accepts_valid_refs(self):
        for ref in VALID_REFS:
            with self.subTest(ref=ref):
                self.assertIsNotNone(self.pattern.search(ref))
                self.validator.validate(ref)

    def test_pattern_rejects_invalid_refs(self):
        for reason, ref in INVALID_REFS.items():
            with self.subTest(reason=reason, ref=ref):
                self.assertIsNone(self.pattern.search(ref), reason)
                self.assertFalse(self.validator.is_valid(ref), reason)

    def test_schema_rejects_non_string(self):
        self.assertFalse(self.validator.is_valid(1751884800))


class TestValidatorScript(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(VALIDATOR_PATH), *args],
            capture_output=True, text=True,
        )

    def test_contract_files_pass(self):
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.startswith("OK:"), proc.stdout)

    def test_valid_ref_accepted(self):
        proc = self._run(VALID_REFS[0])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_invalid_ref_rejected(self):
        proc = self._run(INVALID_REFS["missing @ts"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("invalid snapshot_ref", proc.stderr)

    def test_usage_error(self):
        proc = self._run("--nonsense")
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
