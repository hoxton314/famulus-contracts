#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate a Famulus C3 skill manifest.yaml against manifest.schema.json.

Usage:
  validate_manifest.py MANIFEST_YAML [--schema PATH]

Exit codes:
  0  manifest is valid
  1  manifest failed validation (bad YAML, wrong shape, schema violation)
  2  usage error (bad arguments, unreadable files, broken schema)

Human-readable errors go to stderr; a single summary line goes to stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parent / "manifest.schema.json"


def load_schema(schema_path: str | Path | None = None) -> dict:
    """Load and self-check the manifest JSON Schema.

    Raises OSError, json.JSONDecodeError, or jsonschema SchemaError on problems.
    """
    path = Path(schema_path) if schema_path is not None else DEFAULT_SCHEMA_PATH
    with path.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_manifest_data(data: object, schema: dict | None = None) -> list[str]:
    """Validate an already-parsed manifest document.

    Returns a list of human-readable error strings, each prefixed with the
    JSON path of the failure. An empty list means the manifest is valid.
    """
    if schema is None:
        schema = load_schema()
    if not isinstance(data, dict):
        return [
            "$: manifest document must be a YAML mapping (key: value pairs), "
            f"got {type(data).__name__}"
        ]

    errors: list[str] = []

    # Classic YAML footgun: an unquoted version like 1.0 parses as a float.
    if "version" in data and not isinstance(data["version"], str):
        errors.append(
            f"$.version: parsed as {type(data['version']).__name__} "
            f"({data['version']!r}), not a string — unquoted YAML scalars like "
            '1.0 become numbers; quote it, e.g. version: "1.0.0"'
        )

    validator = Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(data), key=lambda e: e.json_path):
        errors.append(f"{err.json_path}: {err.message}")
    return errors


def validate_manifest_file(
    manifest_path: str | Path, schema_path: str | Path | None = None
) -> list[str]:
    """Load MANIFEST_YAML and validate it against the schema.

    Returns a list of human-readable error strings (empty if valid).
    Raises OSError if the manifest file cannot be read, and OSError /
    json.JSONDecodeError / SchemaError if the schema itself is broken.
    """
    schema = load_schema(schema_path)
    text = Path(manifest_path).read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [f"$: YAML parse error: {exc}"]
    return validate_manifest_data(data, schema=schema)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_manifest.py",
        description="Validate a Famulus C3 skill manifest.yaml "
        "against manifest.schema.json.",
    )
    parser.add_argument(
        "manifest", metavar="MANIFEST_YAML", help="path to the manifest.yaml to validate"
    )
    parser.add_argument(
        "--schema",
        metavar="PATH",
        default=None,
        help="path to an alternative manifest.schema.json "
        "(default: the one next to this script)",
    )
    args = parser.parse_args(argv)

    try:
        errors = validate_manifest_file(args.manifest, schema_path=args.schema)
    except (OSError, json.JSONDecodeError, SchemaError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        print(f"FAIL: {args.manifest}: {len(errors)} error(s)")
        return 1

    print(f"OK: {args.manifest} is a valid C3 skill manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
