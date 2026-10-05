# C5 — permission/tier policy

Contract C5 of the Famulus interface contracts. It defines the shape and
semantics of the tier-policy file that famulus-agentd loads to decide, for
every tool call the agent attempts, which permission tier applies (0 =
read-only/no-auth, 1 = user-authenticated, 2 = admin-authenticated), whether
the call is auto-allowed, prompted, or denied, and whether a C4 snapshot must
be taken first.

The key words MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY in this document
are to be interpreted as described in RFC 2119.

## Consumers

- **famulus-agentd** — loads and enforces the policy; resolves every tool
  name against it before forwarding permission decisions.
- **famulus-broker** (the `mcp__famulus_broker__approve` permission-prompt
  tool) — prompts the user when the resolved behavior is `prompt`.
- **famulus-audit tooling (C1)** — records the resolved decision using the
  mapping table below.
- Any third-party tool that wants to lint, edit, or resolve famulus policies.

## Files

| File | Purpose |
| --- | --- |
| `tier-policy.schema.json` | JSON Schema (draft 2020-12) for the parsed policy YAML. |
| `default-policy.yaml` | The default policy shipped with famulus-agentd; also the canonical fixture. |
| `validate_policy.py` | CLI validator (schema + semantic checks) and the reference `resolve()` implementation. |
| `test_tier_policy.py` | Unit tests (stdlib `unittest`). |
| `README.md` | This spec. |

## Running the validator and tests

From the repo root:

```sh
# Validate a policy file (exit 0 = valid, 1 = invalid, 2 = usage error):
.venv/bin/python tier-policy/validate_policy.py tier-policy/default-policy.yaml

# Validate against an explicit schema copy:
.venv/bin/python tier-policy/validate_policy.py tier-policy/default-policy.yaml --schema tier-policy/tier-policy.schema.json

# Run the tests:
.venv/bin/python -m unittest discover -s tier-policy -v
```

Errors go to stderr; the single summary line goes to stdout.

## Match semantics

`match` patterns use Python `fnmatch.fnmatchcase` semantics: `*` matches any
run of characters (including `_` and nothing), `?` matches exactly one
character, `[seq]` matches one character from the set. Matching is
**case-sensitive**. Patterns are matched against the **full tool name exactly
as the claude CLI reports it** — e.g. `Bash`, `Read`, `WebFetch`, or
`mcp__<server>__<tool>` such as `mcp__famulus_desktop__wallpaper_set`.
Implementations MUST use these semantics (or a byte-for-byte equivalent);
`resolve()` in `validate_policy.py` is the reference implementation and
SHOULD be ported rather than reinvented.

## Evaluation order

1. **`hard_deny`** is checked FIRST and independently of `rules`. It is
   path-based, not tool-based: it is enforced by hooks/polkit on
   file-touching tool inputs. If a tool call would access a `hard_deny` path
   in a denied mode, the call MUST be denied regardless of any rule — no rule
   and no user approval can override it.
2. **`rules`**, top to bottom — the FIRST rule whose `match` glob matches the
   tool name wins; later matching rules are ignored.
3. **`default_rule`** applies when no rule matches. All of its fields are
   required so the fallback is fully explicit.

`behavior: auto-allow` is only valid at tier 0: tiers 1 and 2 require
authentication, so they can never be auto-allowed. This is enforced both in
the schema (`if`/`then`) and by the validator.

`require_snapshot: true` means famulus-agentd MUST obtain a C4 snapshot
(`org.famulus.Snapshot1`) before the tool runs. It is optional on `rules`
entries and defaults to `false`; it is required on `default_rule`.

## Behavior → C1 decision mapping

The C1 audit-log `decision` field records the outcome of applying this
policy:

| C5 behavior / outcome | C1 `decision` |
| --- | --- |
| `auto-allow` | `auto-allow` |
| `prompt`, user answered yes | `user-allow` |
| `prompt`, user answered no | `user-deny` |
| `deny` rule or `hard_deny` hit | `hook-deny` |

## Mandatory hard-deny floor

Every valid famulus policy MUST contain `hard_deny` entries covering at
least:

- `/var/log/famulus/audit/**` with `write` denied — the primary audit chain
  location. The append-only, hash-chained audit log (C1) is the system's
  tamper evidence; if the agent could write to it, the chain would prove
  nothing (audit chain integrity per ADR-5).
- `~/.claude/.credentials.json` with `write` denied at minimum — the user's
  Anthropic credentials (credential protection per ADR-11). The shipped
  default policy also denies `read` on this file, deliberately exceeding the
  write-only baseline to block exfiltration.

`validate_policy.py` rejects any policy missing these entries: a famulus
policy without them is invalid by contract, even if it is schema-valid.

## Stability

Frozen at tag contracts-v1. Changes require an ADR, maintainer review, and a new frozen tag; already-frozen tags are never rewritten.
