#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate ResponseComplete result_json payload files against response-complete.schema.json.

Usage:
  validate_response_complete.py PAYLOAD.json [PAYLOAD.json ...]

Exit codes:
  0  all payloads valid
  1  at least one payload failed validation
  2  usage error (no arguments, or a named file does not exist)
"""

import json
import sys
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parent / "response-complete.schema.json"


def main(argv):
    if len(argv) < 2:
        print(f"usage: {Path(argv[0]).name} PAYLOAD.json [PAYLOAD.json ...]", file=sys.stderr)
        return 2

    paths = [Path(a) for a in argv[1:]]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        for p in missing:
            print(f"{p}: no such file", file=sys.stderr)
        return 2

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    ok = 0
    failed = 0
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            print(f"{path}: not valid JSON: {exc}", file=sys.stderr)
            failed += 1
            continue
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
        if errors:
            failed += 1
            for err in errors:
                where = "/".join(str(part) for part in err.absolute_path) or "(root)"
                print(f"{path}: {where}: {err.message}", file=sys.stderr)
        else:
            ok += 1

    print(f"response-complete: {ok} ok, {failed} failed, {ok + failed} total")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
