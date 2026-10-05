#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reference verifier for the Famulus C1 audit-log hash chain.

Usage:
  validate_chain.py CHAIN_FILE [--schema PATH]

CHAIN_FILE is an append-only NDJSON audit log (one record per line).
--schema defaults to audit-record.schema.json next to this script.

For every line the verifier: parses the JSON (floats are rejected),
validates the record against the schema, checks that ts parses via
datetime.fromisoformat and carries an explicit UTC offset, checks the
genesis rule on the first record, checks prev_hash linkage against the
previous record, and recomputes and compares the record hash.

Exit codes: 0 = chain verified, 1 = validation failure, 2 = usage error.
Failures are reported to stderr with 1-based line numbers; a single
summary line goes to stdout.

The functions canonical_json() and record_hash() are the reference
implementations of the canonicalization and hashing rules in HASHING.md
and may be imported by tests and other tools.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import namedtuple
from datetime import datetime
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover
    print("error: the 'jsonschema' package is required to run this verifier",
          file=sys.stderr)
    sys.exit(2)

GENESIS_PREV_HASH = "0" * 64
DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parent / "audit-record.schema.json"
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

#: One verification failure: 1-based line number, stable category, message.
#: Categories: "empty", "json-parse", "float-forbidden", "schema",
#: "timestamp", "genesis", "chain-link", "hash-mismatch".
ChainError = namedtuple("ChainError", ["line", "category", "message"])


class FloatForbiddenError(ValueError):
    """Raised when a float appears in an audit record (forbidden in v1)."""


def _reject_float(literal):
    raise FloatForbiddenError(
        f"float literal {literal!r} is forbidden in audit records"
    )


def _check_no_floats(obj, path="$"):
    if isinstance(obj, float):
        raise FloatForbiddenError(
            f"float value at {path} is forbidden in audit records"
        )
    if isinstance(obj, dict):
        for key, value in obj.items():
            _check_no_floats(value, f"{path}.{key}")
    elif isinstance(obj, (list, tuple)):
        for index, value in enumerate(obj):
            _check_no_floats(value, f"{path}[{index}]")


def canonical_json(obj):
    """Return the canonical JSON text of obj as defined by HASHING.md.

    Keys sorted by Unicode code point, no insignificant whitespace,
    non-ASCII characters NOT escaped. Raises FloatForbiddenError if any
    float is present (floats are forbidden in hashed records).
    """
    _check_no_floats(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record_hash(prev_hash, record_sans_hash):
    """Compute the C1 record hash, lowercase hex.

    hash = SHA256( ascii_bytes(prev_hash)
                   || canonical_json_bytes(record_sans_hash) )

    record_sans_hash is the record WITHOUT its "hash" member but WITH
    its "prev_hash" member (prev_hash intentionally enters the input
    twice; see HASHING.md and ADR-5).
    """
    data = prev_hash.encode("ascii") + canonical_json(record_sans_hash).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _timestamp_ok(ts):
    """True if ts parses via datetime.fromisoformat with an explicit offset."""
    try:
        parsed = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def verify_chain(chain_path, schema_path=None):
    """Verify an audit-log NDJSON file.

    Returns (record_count, errors) where errors is a list of ChainError.
    An empty errors list means the chain verified.
    """
    schema_path = Path(schema_path) if schema_path is not None else DEFAULT_SCHEMA_PATH
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    errors = []
    count = 0
    parsed_records = 0
    prev_record_hash = None  # hash of the previous record, None if unknown

    with open(chain_path, "r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            count += 1
            text = line.rstrip("\n")
            try:
                record = json.loads(text, parse_float=_reject_float)
            except FloatForbiddenError as exc:
                errors.append(ChainError(lineno, "float-forbidden", str(exc)))
                prev_record_hash = None
                parsed_records += 1
                continue
            except json.JSONDecodeError as exc:
                errors.append(ChainError(lineno, "json-parse", str(exc)))
                prev_record_hash = None
                parsed_records += 1
                continue
            parsed_records += 1

            if not isinstance(record, dict):
                errors.append(ChainError(
                    lineno, "schema", "record is not a JSON object"))
                prev_record_hash = None
                continue

            for err in sorted(validator.iter_errors(record),
                              key=lambda e: list(e.absolute_path)):
                location = "/".join(str(p) for p in err.absolute_path) or "(root)"
                errors.append(ChainError(lineno, "schema",
                                         f"{location}: {err.message}"))

            ts = record.get("ts")
            if isinstance(ts, str) and not _timestamp_ok(ts):
                errors.append(ChainError(
                    lineno, "timestamp",
                    f"ts {ts!r} does not parse as an RFC 3339 timestamp "
                    "with an explicit UTC offset"))

            this_prev = record.get("prev_hash")
            this_hash = record.get("hash")
            prev_is_hex = isinstance(this_prev, str) and _SHA256_HEX_RE.match(this_prev)
            hash_is_hex = isinstance(this_hash, str) and _SHA256_HEX_RE.match(this_hash)

            if parsed_records == 1 and this_prev != GENESIS_PREV_HASH:
                errors.append(ChainError(
                    lineno, "genesis",
                    f"first record's prev_hash must be 64 ASCII '0' "
                    f"characters, got {this_prev!r}"))
            elif prev_record_hash is not None and this_prev != prev_record_hash:
                errors.append(ChainError(
                    lineno, "chain-link",
                    f"prev_hash {this_prev!r} does not equal the previous "
                    f"record's hash {prev_record_hash!r}"))

            if prev_is_hex and hash_is_hex:
                record_sans_hash = {k: v for k, v in record.items() if k != "hash"}
                computed = record_hash(this_prev, record_sans_hash)
                if computed != this_hash:
                    errors.append(ChainError(
                        lineno, "hash-mismatch",
                        f"stored hash {this_hash} does not match recomputed "
                        f"hash {computed}"))

            prev_record_hash = this_hash if hash_is_hex else None

    if count == 0:
        errors.append(ChainError(0, "empty", "log contains no records"))

    return count, errors


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="validate_chain.py",
        description="Verify a Famulus C1 audit-log hash chain (NDJSON).")
    parser.add_argument("chain_file", metavar="CHAIN_FILE",
                        help="append-only NDJSON audit log to verify")
    parser.add_argument("--schema", metavar="PATH", default=None,
                        help="path to audit-record.schema.json "
                             "(default: next to this script)")
    args = parser.parse_args(argv)

    chain_path = Path(args.chain_file)
    schema_path = Path(args.schema) if args.schema else DEFAULT_SCHEMA_PATH
    if not chain_path.is_file():
        print(f"error: chain file not found: {chain_path}", file=sys.stderr)
        return 2
    if not schema_path.is_file():
        print(f"error: schema file not found: {schema_path}", file=sys.stderr)
        return 2

    count, errors = verify_chain(chain_path, schema_path)
    if errors:
        for err in errors:
            print(f"line {err.line}: {err.category}: {err.message}",
                  file=sys.stderr)
        print(f"FAIL: {count} records, {len(errors)} error(s)")
        return 1
    print(f"OK: {count} records, chain verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
