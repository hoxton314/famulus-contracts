#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validator for contract C4 (dbus-snapshot).

Usage:
  validate_snapshot_contract.py [SNAPSHOT_REF ...]

With no arguments, validates the contract files in this directory:
  - org.famulus.Snapshot1.xml begins with the freedesktop introspection
    DOCTYPE, is well-formed XML, and (when gdbus-codegen is installed)
    passes `gdbus-codegen --interface-info-body`.
  - snapshot-ref.schema.json is a valid JSON Schema (draft 2020-12).

Positional arguments are additionally validated as snapshot_ref strings
against the schema pattern.

Exit codes: 0 success, 1 validation failure, 2 usage error.
Errors go to stderr; a single summary line goes to stdout.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
XML_PATH = HERE / "org.famulus.Snapshot1.xml"
SCHEMA_PATH = HERE / "snapshot-ref.schema.json"

DOCTYPE_PREFIX = (
    '<!DOCTYPE node PUBLIC '
    '"-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"'
)

USAGE = "usage: validate_snapshot_contract.py [SNAPSHOT_REF ...]"


def fail(errors, msg):
    errors.append(msg)
    print(f"error: {msg}", file=sys.stderr)


def check_contract_files(errors):
    # --- introspection XML ---
    try:
        text = XML_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        fail(errors, f"cannot read {XML_PATH}: {exc}")
        return
    if not text.startswith(DOCTYPE_PREFIX):
        fail(errors, f"{XML_PATH.name}: missing freedesktop introspection DOCTYPE")
    try:
        ET.fromstring(text)
    except ET.ParseError as exc:
        fail(errors, f"{XML_PATH.name}: not well-formed XML: {exc}")

    codegen = shutil.which("gdbus-codegen")
    if codegen:
        proc = subprocess.run(
            [codegen, "--interface-info-body", "--output", os.devnull,
             str(XML_PATH)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            fail(errors,
                 f"{XML_PATH.name}: gdbus-codegen failed: {proc.stderr.strip()}")
    else:
        print("note: gdbus-codegen not installed; codegen check skipped",
              file=sys.stderr)

    # --- schema ---
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(errors, f"cannot read {SCHEMA_PATH}: {exc}")
        return None
    try:
        import jsonschema
        jsonschema.validators.Draft202012Validator.check_schema(schema)
    except ImportError:
        print("note: jsonschema not installed; check_schema skipped",
              file=sys.stderr)
    except Exception as exc:  # jsonschema.SchemaError
        fail(errors, f"{SCHEMA_PATH.name}: invalid JSON Schema: {exc}")
    return schema


def main(argv):
    args = argv[1:]
    if any(a.startswith("-") for a in args):
        print(USAGE, file=sys.stderr)
        return 2

    errors = []
    schema = check_contract_files(errors)

    checked_refs = 0
    if args:
        pattern = None
        if isinstance(schema, dict) and isinstance(schema.get("pattern"), str):
            try:
                pattern = re.compile(schema["pattern"])
            except re.error as exc:
                fail(errors, f"{SCHEMA_PATH.name}: pattern does not compile: {exc}")
        if pattern is None:
            fail(errors, "cannot validate snapshot_ref arguments: no usable pattern")
        else:
            for ref in args:
                checked_refs += 1
                if not pattern.search(ref):
                    fail(errors, f"invalid snapshot_ref: {ref!r}")

    if errors:
        print(f"FAIL: {len(errors)} error(s) "
              f"(contract files + {checked_refs} ref(s) checked)")
        return 1
    print(f"OK: contract files valid, {checked_refs} snapshot_ref(s) checked")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
