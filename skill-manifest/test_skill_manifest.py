#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the C3 skill-manifest contract (schema, examples, validator).

Run from the repo root with:
  .venv/bin/python -m unittest discover -s skill-manifest -v
"""
from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

import validate_manifest

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "manifest.schema.json"
WALLPAPER_EXAMPLE = HERE / "examples" / "wallpaper" / "manifest.yaml"
INSTALL_EXAMPLE = HERE / "examples" / "install-software" / "manifest.yaml"

REQUIRED_FIELDS = [
    "name",
    "version",
    "tier",
    "mutates_system",
    "polkit_actions",
    "files_touched",
    "network_access",
    "description",
]

# A minimal valid tier-1 manifest used as the base for negative tests.
BASE_MANIFEST = {
    "name": "example-skill",
    "version": "1.2.3",
    "tier": 1,
    "mutates_system": True,
    "polkit_actions": ["org.famulus.net.wifi-connect"],
    "files_touched": ["/etc/NetworkManager/system-connections/*"],
    "network_access": False,
    "description": "Example skill manifest used by the C3 contract tests.",
}


def manifest_with(**overrides) -> dict:
    data = copy.deepcopy(BASE_MANIFEST)
    data.update(overrides)
    return data


class TestSchema(unittest.TestCase):
    def test_schema_is_valid_draft_2020_12(self) -> None:
        schema = validate_manifest.load_schema()
        # load_schema already runs check_schema; assert explicitly anyway.
        Draft202012Validator.check_schema(schema)
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(
            schema["$id"], "https://famulus.dev/contracts/v1/manifest.schema.json"
        )


class TestExamples(unittest.TestCase):
    def test_wallpaper_example_is_valid(self) -> None:
        errors = validate_manifest.validate_manifest_file(WALLPAPER_EXAMPLE)
        self.assertEqual(errors, [])

    def test_install_software_example_is_valid(self) -> None:
        errors = validate_manifest.validate_manifest_file(INSTALL_EXAMPLE)
        self.assertEqual(errors, [])

    def test_base_manifest_is_valid(self) -> None:
        self.assertEqual(validate_manifest.validate_manifest_data(BASE_MANIFEST), [])


class TestNegatives(unittest.TestCase):
    def assert_invalid(self, data: object) -> list[str]:
        errors = validate_manifest.validate_manifest_data(data)
        self.assertTrue(errors, f"expected validation errors for {data!r}")
        return errors

    def test_bad_semver_strings(self) -> None:
        for bad in ["1.0", "v1.0.0", "1.0.0.0", "01.0.0", ""]:
            with self.subTest(version=bad):
                self.assert_invalid(manifest_with(version=bad))

    def test_version_as_float_reports_quote_hint(self) -> None:
        errors = self.assert_invalid(manifest_with(version=1.0))
        self.assertTrue(
            any("quote it" in e for e in errors),
            f"expected a 'quote it' hint in {errors!r}",
        )

    def test_tier_3_rejected(self) -> None:
        self.assert_invalid(manifest_with(tier=3))

    def test_missing_each_required_field(self) -> None:
        for field in REQUIRED_FIELDS:
            with self.subTest(missing=field):
                data = copy.deepcopy(BASE_MANIFEST)
                del data[field]
                errors = self.assert_invalid(data)
                self.assertTrue(
                    any(field in e for e in errors),
                    f"expected an error mentioning {field!r} in {errors!r}",
                )

    def test_extra_top_level_field_rejected(self) -> None:
        self.assert_invalid(manifest_with(sandbox=True))

    def test_tier_0_with_polkit_action_rejected(self) -> None:
        self.assert_invalid(
            manifest_with(
                tier=0,
                mutates_system=False,
                polkit_actions=["org.famulus.net.wifi-connect"],
            )
        )

    def test_tier_1_without_polkit_action_rejected(self) -> None:
        self.assert_invalid(manifest_with(polkit_actions=[]))

    def test_mutates_system_true_with_tier_0_rejected(self) -> None:
        self.assert_invalid(
            manifest_with(tier=0, mutates_system=True, polkit_actions=[])
        )

    def test_polkit_action_outside_famulus_namespace_rejected(self) -> None:
        self.assert_invalid(
            manifest_with(
                polkit_actions=["org.freedesktop.NetworkManager.settings.modify.system"]
            )
        )

    def test_duplicate_polkit_actions_rejected(self) -> None:
        self.assert_invalid(
            manifest_with(
                polkit_actions=[
                    "org.famulus.net.wifi-connect",
                    "org.famulus.net.wifi-connect",
                ]
            )
        )

    def test_bad_name_rejected(self) -> None:
        for bad in ["Wallpaper", "-wallpaper", "wall paper", "a" * 64]:
            with self.subTest(name=bad):
                self.assert_invalid(manifest_with(name=bad))

    def test_non_mapping_document_rejected(self) -> None:
        errors = self.assert_invalid(["not", "a", "mapping"])
        self.assertIn("mapping", errors[0])


class TestValidatorCli(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(HERE / "validate_manifest.py"), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_ok_on_valid_example(self) -> None:
        proc = self.run_cli(str(WALLPAPER_EXAMPLE))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK", proc.stdout)

    def test_cli_fails_on_unquoted_version_yaml_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.yaml"
            manifest.write_text(
                "name: example-skill\n"
                "version: 1.0\n"
                "tier: 1\n"
                "mutates_system: true\n"
                "polkit_actions:\n"
                '  - "org.famulus.net.wifi-connect"\n'
                "files_touched: []\n"
                "network_access: false\n"
                "description: Unquoted version footgun.\n",
                encoding="utf-8",
            )
            proc = self.run_cli(str(manifest))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("quote it", proc.stderr)
        self.assertIn("FAIL", proc.stdout)

    def test_cli_usage_error_on_missing_file(self) -> None:
        proc = self.run_cli("/nonexistent/manifest.yaml")
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
