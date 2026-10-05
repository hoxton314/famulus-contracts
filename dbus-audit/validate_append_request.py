#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validator for contract C7 (dbus-audit) Append payloads.

Usage:
  validate_append_request.py PAYLOAD.json [PAYLOAD.json ...]

Each file must hold one JSON object valid against append-request.schema.json
and containing no floats anywhere (C1 HASHING.md section 2).

Exit codes: 0 all valid, 1 validation failure, 2 usage error.
Errors go to stderr; a single summary line goes to stdout.
"""

import json
import sys
from pathlib import Path

import jsonschema

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "append-request.schema.json"


def _reject_float(literal):
    raise ValueError(f"float literal {literal!r} is forbidden in audit records")


def validate_payload(text, validator):
    """Return a list of error strings for one payload (empty when valid)."""
    try:
        obj = json.loads(text, parse_float=_reject_float)
    except ValueError as exc:
        return [str(exc)]
    return [f"{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message}"
            for e in validator.iter_errors(obj)]


def main(argv):
    if not argv:
        print("usage: validate_append_request.py PAYLOAD.json [PAYLOAD.json ...]",
              file=sys.stderr)
        return 2
    validator = jsonschema.Draft202012Validator(
        json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    failed = 0
    for name in argv:
        path = Path(name)
        if not path.is_file():
            print(f"error: no such file: {name}", file=sys.stderr)
            return 2
        errors = validate_payload(path.read_text(encoding="utf-8"), validator)
        for err in errors:
            print(f"{name}: {err}", file=sys.stderr)
        failed += bool(errors)
    if failed:
        print(f"FAIL: {failed} of {len(argv)} payload(s) invalid")
        return 1
    print(f"OK: {len(argv)} valid C7 append payload(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
