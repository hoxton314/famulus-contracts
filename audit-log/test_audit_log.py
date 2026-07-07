#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the C1 audit-log contract (schema, verifier, fixtures)."""

import contextlib
import io
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

import validate_chain
from validate_chain import (
    GENESIS_PREV_HASH,
    canonical_json,
    record_hash,
    verify_chain,
)

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "audit-record.schema.json"
FIXTURES = HERE / "fixtures"
HASHING_MD = HERE / "HASHING.md"

# Test vector from HASHING.md section 8 (genesis record of the valid chain).
VECTOR_EXPECTED_HASH = (
    "f87b9447c99a26bd0fa44f49a1dc073527bd1cdd9964fca29a1286880d075b3c"
)
VECTOR_RECORD_SANS_HASH = {
    "ts": "2026-07-07T14:03:22.114Z",
    "event_id": "019f3ce3-fc82-7a1c-8f3b-1d2e4a6c8b0f",
    "conversation_id": "b3f9c2e8-4d17-4f6a-9c05-2e8b7a1d4c66",
    "actor": "agent",
    "tool": "mcp__famulus_desktop__wallpaper_set",
    "input_redacted": {"uri": "file:///home/user/Pictures/aurora.png"},
    "decision": "auto-allow",
    "tier": 0,
    "snapshot_ref": None,
    "deployment_before": None,
    "result": "ok",
    "prev_hash": GENESIS_PREV_HASH,
}


def load_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def base_record(**overrides):
    """A schema-valid record (hash values are schema-valid dummies)."""
    record = dict(VECTOR_RECORD_SANS_HASH)
    record["hash"] = VECTOR_EXPECTED_HASH
    record.update(overrides)
    return record


class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_schema()
        cls.validator = Draft202012Validator(cls.schema)

    def assert_valid(self, record):
        errors = list(self.validator.iter_errors(record))
        self.assertEqual(errors, [], f"expected valid, got: "
                                     f"{[e.message for e in errors]}")

    def assert_invalid(self, record):
        errors = list(self.validator.iter_errors(record))
        self.assertNotEqual(errors, [], "expected schema errors, got none")

    def test_schema_is_valid_draft_2020_12(self):
        Draft202012Validator.check_schema(self.schema)

    def test_base_record_is_schema_valid(self):
        self.assert_valid(base_record())

    def test_extra_field_rejected(self):
        self.assert_invalid(base_record(extra="nope"))

    def test_actor_enum_rejects_out_of_range(self):
        self.assert_invalid(base_record(actor="robot"))

    def test_decision_enum_rejects_out_of_range(self):
        self.assert_invalid(base_record(decision="allow"))

    def test_tier_enum_rejects_out_of_range(self):
        self.assert_invalid(base_record(tier=3))

    def test_result_enum_rejects_out_of_range(self):
        self.assert_invalid(base_record(result="failed"))

    def test_snapshot_ref_accepts_shared_example(self):
        self.assert_valid(base_record(
            snapshot_ref="famulus-snap/019811a2-7c3e-7d10-9b8a-3f2e1d0c4b5a"
                         "/etc+var@1751884800"))

    def test_snapshot_ref_accepts_null(self):
        self.assert_valid(base_record(snapshot_ref=None))

    def test_snapshot_ref_rejects_garbage(self):
        self.assert_invalid(base_record(snapshot_ref="famulus-snap/x/etc@12"))

    def test_snapshot_ref_rejects_uppercase_uuid(self):
        self.assert_invalid(base_record(
            snapshot_ref="famulus-snap/019811A2-7C3E-7D10-9B8A-3F2E1D0C4B5A"
                         "/etc+var@1751884800"))


class CanonicalizationTests(unittest.TestCase):
    def test_keys_sorted_by_code_point(self):
        self.assertEqual(canonical_json({"b": 1, "a": 2, "Z": 3}),
                         '{"Z":3,"a":2,"b":1}')

    def test_non_ascii_not_escaped(self):
        self.assertEqual(canonical_json({"name": "żółć"}), '{"name":"żółć"}')

    def test_separators_no_whitespace(self):
        self.assertEqual(canonical_json({"a": [1, 2], "b": {"c": 0}}),
                         '{"a":[1,2],"b":{"c":0}}')

    def test_float_rejected_at_top_level(self):
        with self.assertRaises(ValueError):
            canonical_json({"x": 1.5})

    def test_float_rejected_when_nested(self):
        with self.assertRaises(ValueError):
            canonical_json({"input_redacted": {"volume": [0.7]}})


class TestVectorTests(unittest.TestCase):
    def test_worked_example_hash_reproduces(self):
        self.assertEqual(
            record_hash(GENESIS_PREV_HASH, VECTOR_RECORD_SANS_HASH),
            VECTOR_EXPECTED_HASH)

    def test_hashing_md_shows_the_same_hash(self):
        text = HASHING_MD.read_text(encoding="utf-8")
        self.assertIn(VECTOR_EXPECTED_HASH, text)

    def test_vector_matches_valid_chain_genesis(self):
        first_line = (FIXTURES / "valid-chain.ndjson").read_text(
            encoding="utf-8").splitlines()[0]
        record = json.loads(first_line)
        self.assertEqual(record["hash"], VECTOR_EXPECTED_HASH)
        record_sans_hash = {k: v for k, v in record.items() if k != "hash"}
        self.assertEqual(record_sans_hash, VECTOR_RECORD_SANS_HASH)


class VerifierTests(unittest.TestCase):
    def verify(self, name):
        return verify_chain(FIXTURES / name, SCHEMA_PATH)

    def test_valid_chain_verifies(self):
        count, errors = self.verify("valid-chain.ndjson")
        self.assertEqual(errors, [])
        self.assertEqual(count, 4)

    def test_tampered_payload_fails_with_hash_mismatch(self):
        count, errors = self.verify("tampered-payload.ndjson")
        self.assertEqual(count, 4)
        self.assertEqual([(e.line, e.category) for e in errors],
                         [(2, "hash-mismatch")])

    def test_broken_link_fails_with_chain_link(self):
        count, errors = self.verify("broken-link.ndjson")
        self.assertEqual(count, 4)
        self.assertEqual([(e.line, e.category) for e in errors],
                         [(2, "chain-link")])

    def test_bad_genesis_fails_with_genesis(self):
        count, errors = self.verify("bad-genesis.ndjson")
        self.assertEqual(count, 4)
        self.assertEqual([(e.line, e.category) for e in errors],
                         [(1, "genesis")])

    def test_timestamp_without_offset_rejected(self):
        record_sans = dict(VECTOR_RECORD_SANS_HASH, ts="2026-07-07T14:03:22")
        record = dict(record_sans,
                      hash=record_hash(GENESIS_PREV_HASH, record_sans))
        chain_file = FIXTURES.parent / "_tmp_ts.ndjson"
        try:
            chain_file.write_text(canonical_json(record) + "\n",
                                  encoding="utf-8")
            _, errors = verify_chain(chain_file, SCHEMA_PATH)
            self.assertEqual([(e.line, e.category) for e in errors],
                             [(1, "timestamp")])
        finally:
            chain_file.unlink(missing_ok=True)

    def test_float_in_record_rejected(self):
        line = ('{"ts":"2026-07-07T14:03:22.114Z","input_redacted":'
                '{"volume":0.7}}')
        chain_file = FIXTURES.parent / "_tmp_float.ndjson"
        try:
            chain_file.write_text(line + "\n", encoding="utf-8")
            _, errors = verify_chain(chain_file, SCHEMA_PATH)
            self.assertIn("float-forbidden", [e.category for e in errors])
        finally:
            chain_file.unlink(missing_ok=True)

    def test_cli_exit_codes(self):
        def run(name):
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                return validate_chain.main([str(FIXTURES / name)])

        self.assertEqual(run("valid-chain.ndjson"), 0)
        self.assertEqual(run("bad-genesis.ndjson"), 1)
        self.assertEqual(run("does-not-exist.ndjson"), 2)

    def test_cli_success_summary_line(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = validate_chain.main([str(FIXTURES / "valid-chain.ndjson")])
        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "OK: 4 records, chain verified\n")


if __name__ == "__main__":
    unittest.main()
