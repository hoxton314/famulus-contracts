#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validator and reference resolver for the Famulus C5 tier policy.

Usage:
    validate_policy.py POLICY_YAML [--schema PATH]

Exit codes: 0 = valid, 1 = validation failure, 2 = usage error.
Human-readable errors go to stderr; a single summary line goes to stdout.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path

import jsonschema
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SCHEMA_PATH = SCRIPT_DIR / "tier-policy.schema.json"

# Contract-mandated hard-deny floor: (path, access mode that MUST be denied).
# Audit chain integrity per ADR-5; credential protection per ADR-11.
HARD_DENY_FLOOR = (
    ("/var/log/famulus/audit/**", "write"),
    ("~/.claude/.credentials.json", "write"),
)


def resolve(policy, tool_name):
    """Reference first-match-wins resolver (port me, don't reinvent me).

    Returns the first entry of policy["rules"] whose ``match`` glob matches
    ``tool_name`` (case-sensitive fnmatch), else policy["default_rule"].
    hard_deny is path-based and enforced separately; it is NOT consulted here.
    """
    for rule in policy["rules"]:
        if fnmatch.fnmatchcase(tool_name, rule["match"]):
            return rule
    return policy["default_rule"]


def schema_errors(policy, schema):
    """Validate ``policy`` against ``schema``; return a list of error strings."""
    validator = jsonschema.Draft202012Validator(schema)
    errors = []
    for err in validator.iter_errors(policy):
        where = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"schema: {where}: {err.message}")
    return errors


def _auto_allow_errors(rule, where):
    if rule.get("behavior") == "auto-allow" and rule.get("tier") != 0:
        return [
            f"{where}: behavior 'auto-allow' is only valid at tier 0 — "
            f"tier {rule.get('tier')!r} requires authentication and can "
            "never be auto-allowed"
        ]
    return []


def semantic_errors(policy):
    """Contract checks beyond the JSON Schema; return a list of error strings.

    Deliberately defensive (tolerates schema-invalid shapes) so its findings
    can be reported alongside schema errors in a single pass.
    """
    errors = []
    if not isinstance(policy, dict):
        return errors

    rules = policy.get("rules")
    if isinstance(rules, list):
        seen = {}
        for i, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            match = rule.get("match")
            if isinstance(match, str):
                if match in seen:
                    errors.append(
                        f"rules[{i}]: duplicate match pattern {match!r} "
                        f"(already used by rules[{seen[match]}]; first match "
                        "wins, so a duplicate is a dead rule)"
                    )
                else:
                    seen[match] = i
            errors.extend(_auto_allow_errors(rule, f"rules[{i}]"))

    default_rule = policy.get("default_rule")
    if isinstance(default_rule, dict):
        errors.extend(_auto_allow_errors(default_rule, "default_rule"))

    hard_deny = policy.get("hard_deny")
    entries = hard_deny if isinstance(hard_deny, list) else []
    for path, mode in HARD_DENY_FLOOR:
        covered = any(
            isinstance(entry, dict)
            and entry.get("path") == path
            and isinstance(entry.get("access"), list)
            and mode in entry["access"]
            for entry in entries
        )
        if not covered:
            errors.append(
                f"hard_deny: mandatory floor entry missing — an entry with "
                f"path {path!r} denying {mode!r} access is required by "
                "contract C5 (audit chain integrity per ADR-5, credential "
                "protection per ADR-11); a famulus policy without it is "
                "invalid"
            )
    return errors


def validate_policy(policy, schema):
    """Full contract validation; returns all errors (empty list == valid)."""
    return schema_errors(policy, schema) + semantic_errors(policy)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="validate_policy.py",
        description="Validate a Famulus C5 tier-policy YAML file.",
    )
    parser.add_argument(
        "policy", metavar="POLICY_YAML", help="path to the policy YAML file"
    )
    parser.add_argument(
        "--schema",
        metavar="PATH",
        default=None,
        help="JSON Schema to validate against "
        "(default: tier-policy.schema.json next to this script)",
    )
    args = parser.parse_args(argv)

    schema_path = Path(args.schema) if args.schema else DEFAULT_SCHEMA_PATH
    policy_path = Path(args.policy)

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: cannot load schema {schema_path}: {exc}", file=sys.stderr)
        return 2

    try:
        text = policy_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot read policy {policy_path}: {exc}", file=sys.stderr)
        return 2

    try:
        policy = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        print(f"{policy_path}: not valid YAML: {exc}", file=sys.stderr)
        print(f"FAIL: {policy_path.name}: 1 error")
        return 1

    errors = validate_policy(policy, schema)
    if errors:
        for err in errors:
            print(f"{policy_path}: {err}", file=sys.stderr)
        print(f"FAIL: {policy_path.name}: {len(errors)} error(s)")
        return 1

    print(
        f"OK: {policy_path.name}: valid C5 tier policy "
        f"(version {policy['version']}, {len(policy['rules'])} rules, "
        f"{len(policy['hard_deny'])} hard-deny entries)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
