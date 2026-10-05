#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the Famulus C5 tier-policy contract.

Run from the repo root:
    .venv/bin/python -m unittest discover -s tier-policy -v
"""

import copy
import fnmatch
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import jsonschema
import yaml

import validate_policy

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "tier-policy.schema.json"
POLICY_PATH = HERE / "default-policy.yaml"


def load_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def load_policy():
    return yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))


class TestSchema(unittest.TestCase):
    def test_schema_passes_check_schema(self):
        schema = load_schema()
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_schema_ids(self):
        schema = load_schema()
        self.assertEqual(
            schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
        )
        self.assertEqual(
            schema["$id"],
            "https://famulus.dev/contracts/v1/tier-policy.schema.json",
        )


class TestDefaultPolicy(unittest.TestCase):
    def test_default_policy_passes_full_validator(self):
        errors = validate_policy.validate_policy(load_policy(), load_schema())
        self.assertEqual(errors, [])

    def test_cli_exits_zero_with_summary_line(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = validate_policy.main([str(POLICY_PATH)])
        self.assertEqual(rc, 0)
        out = buf.getvalue().strip().splitlines()
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("OK: default-policy.yaml"))


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy()

    def resolve(self, tool_name):
        return validate_policy.resolve(self.policy, tool_name)

    def test_wallpaper_set_is_tier0_auto_allow(self):
        rule = self.resolve("mcp__famulus_desktop__wallpaper_set")
        self.assertEqual(rule["tier"], 0)
        self.assertEqual(rule["behavior"], "auto-allow")
        self.assertEqual(rule["match"], "mcp__famulus_*__wallpaper_*")

    def test_wifi_connect_is_tier1_prompt(self):
        rule = self.resolve("mcp__famulus_net__wifi_connect")
        self.assertEqual(rule["tier"], 1)
        self.assertEqual(rule["behavior"], "prompt")

    def test_rpm_ostree_install_is_tier2_prompt_with_snapshot(self):
        rule = self.resolve("mcp__famulus_pkg__rpm_ostree_install")
        self.assertEqual(rule["tier"], 2)
        self.assertEqual(rule["behavior"], "prompt")
        self.assertTrue(rule.get("require_snapshot", False))

    def test_bash_is_tier2_with_snapshot(self):
        rule = self.resolve("Bash")
        self.assertEqual(rule["tier"], 2)
        self.assertTrue(rule.get("require_snapshot", False))

    def test_unknown_tool_falls_through_to_default_rule(self):
        rule = self.resolve("SomeUnknownTool")
        self.assertIs(rule, self.policy["default_rule"])
        self.assertEqual(rule["tier"], 2)
        self.assertEqual(rule["behavior"], "prompt")
        self.assertTrue(rule["require_snapshot"])

    def test_rule_order_first_match_wins(self):
        # This name matches BOTH the tier-1 wifi rule and the tier-2 network
        # rule. The wifi rule comes first in `rules`, so first-match-wins must
        # resolve to tier 1. Reordering the tier-2 network rule above the
        # tier-1 wifi rule would break this test.
        name = "mcp__famulus_net__wifi__network_reset"
        self.assertTrue(fnmatch.fnmatchcase(name, "mcp__famulus_*__wifi_*"))
        self.assertTrue(fnmatch.fnmatchcase(name, "mcp__famulus_*__network_*"))
        rule = self.resolve(name)
        self.assertEqual(rule["match"], "mcp__famulus_*__wifi_*")
        self.assertEqual(rule["tier"], 1)

    def test_network_wifi_reset_hits_network_rule(self):
        # Single underscore before "wifi": the "__wifi_" pattern does NOT
        # match, so this name falls through to the tier-2 network rule.
        rule = self.resolve("mcp__famulus_net__network_wifi_reset")
        self.assertEqual(rule["match"], "mcp__famulus_*__network_*")
        self.assertEqual(rule["tier"], 2)
        self.assertTrue(rule.get("require_snapshot", False))


class TestNegatives(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()
        self.policy = load_policy()

    def errors(self, policy):
        return validate_policy.validate_policy(policy, self.schema)

    def test_missing_credentials_hard_deny_fails(self):
        bad = copy.deepcopy(self.policy)
        bad["hard_deny"] = [
            entry
            for entry in bad["hard_deny"]
            if entry["path"] != "~/.claude/.credentials.json"
        ]
        errs = self.errors(bad)
        self.assertTrue(
            any("~/.claude/.credentials.json" in e for e in errs), errs
        )

    def test_missing_audit_hard_deny_fails(self):
        bad = copy.deepcopy(self.policy)
        bad["hard_deny"] = [
            entry
            for entry in bad["hard_deny"]
            if entry["path"] != "/var/log/famulus/audit/**"
        ]
        errs = self.errors(bad)
        self.assertTrue(
            any("/var/log/famulus/audit/**" in e for e in errs), errs
        )

    def test_auto_allow_at_tier1_fails(self):
        bad = copy.deepcopy(self.policy)
        bad["rules"].insert(
            0, {"match": "UniqueTool", "tier": 1, "behavior": "auto-allow"}
        )
        errs = self.errors(bad)
        # Rejected by the schema if/then AND flagged with a friendly message.
        self.assertTrue(any(e.startswith("schema:") for e in errs), errs)
        self.assertTrue(
            any("auto-allow' is only valid at tier 0" in e for e in errs), errs
        )

    def test_auto_allow_default_rule_at_tier2_fails(self):
        bad = copy.deepcopy(self.policy)
        bad["default_rule"] = {
            "tier": 2,
            "behavior": "auto-allow",
            "require_snapshot": True,
        }
        errs = self.errors(bad)
        self.assertTrue(any("default_rule" in e for e in errs), errs)

    def test_duplicate_match_fails(self):
        bad = copy.deepcopy(self.policy)
        bad["rules"].append(dict(bad["rules"][0]))
        errs = self.errors(bad)
        self.assertTrue(any("duplicate match pattern" in e for e in errs), errs)

    def test_version_2_fails(self):
        bad = copy.deepcopy(self.policy)
        bad["version"] = 2
        errs = self.errors(bad)
        self.assertTrue(any("version" in e for e in errs), errs)

    def test_extra_top_level_key_fails(self):
        bad = copy.deepcopy(self.policy)
        bad["extra_key"] = True
        errs = self.errors(bad)
        self.assertTrue(
            any("Additional properties" in e or "extra_key" in e for e in errs),
            errs,
        )

    def test_cli_exits_one_on_invalid_policy(self):
        bad = copy.deepcopy(self.policy)
        bad["version"] = 2
        with tempfile.TemporaryDirectory() as tmp:
            bad_path = Path(tmp) / "invalid-policy.yaml"
            bad_path.write_text(yaml.safe_dump(bad), encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = validate_policy.main([str(bad_path)])
        self.assertEqual(rc, 1)
        self.assertTrue(out.getvalue().startswith("FAIL:"))
        self.assertIn("version", err.getvalue())

    def test_cli_exits_two_on_malformed_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "bad.schema.json"
            schema_path.write_text(json.dumps({"type": "not-a-type"}), encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = validate_policy.main(
                    [str(validate_policy.DEFAULT_SCHEMA_PATH.parent / "default-policy.yaml"),
                     "--schema", str(schema_path)])
        self.assertEqual(rc, 2)
        self.assertIn("invalid schema", err.getvalue())


if __name__ == "__main__":
    unittest.main()
