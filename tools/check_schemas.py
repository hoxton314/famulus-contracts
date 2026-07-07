#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Meta-schema check: every *.schema.json in the repo must be a valid
JSON Schema draft 2020-12 document with the repo's $schema/$id conventions."""

import json
import sys
from pathlib import Path

from jsonschema import validators

REPO_ROOT = Path(__file__).resolve().parent.parent
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
ID_PREFIX = "https://famulus.dev/contracts/v1/"


def main() -> int:
    schema_files = sorted(
        p for p in REPO_ROOT.rglob("*.schema.json") if ".venv" not in p.parts
    )
    if not schema_files:
        print("error: no *.schema.json files found", file=sys.stderr)
        return 1

    errors = 0
    for path in schema_files:
        rel = path.relative_to(REPO_ROOT)
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"error: {rel}: not valid JSON: {exc}", file=sys.stderr)
            errors += 1
            continue
        if schema.get("$schema") != DRAFT_2020_12:
            print(f"error: {rel}: $schema must be {DRAFT_2020_12}", file=sys.stderr)
            errors += 1
        expected_id = ID_PREFIX + path.name
        if schema.get("$id") != expected_id:
            print(f"error: {rel}: $id must be {expected_id}", file=sys.stderr)
            errors += 1
        try:
            validators.validator_for(schema).check_schema(schema)
        except Exception as exc:  # jsonschema.SchemaError
            print(f"error: {rel}: fails its meta-schema: {exc}", file=sys.stderr)
            errors += 1

    if errors:
        print(f"FAIL: {errors} problem(s) across {len(schema_files)} schema file(s)")
        return 1
    print(f"OK: {len(schema_files)} schema file(s) pass the draft 2020-12 meta-schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())
