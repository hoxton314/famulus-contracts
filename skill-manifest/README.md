# C3 — skill manifest (`manifest.yaml`)

The key words MUST, SHOULD, and MAY in this document are to be interpreted as
described in RFC 2119.

## What this contract is

Contract C3 defines the shape of the `manifest.yaml` that sits NEXT TO
`SKILL.md` in each skill directory of famulus-skills. The manifest declares a
skill's identity (`name`, `version`, `description`) and its security posture:

- `tier` — the HIGHEST permission tier (0/1/2) any action of the skill may
  require. The runtime (famulus-agentd) enforces tiers via the C5
  permission/tier policy.
- `mutates_system` — if true, the skill can mutate state under `/etc` or
  `/var`, and the runtime MUST take a C4 snapshot (`org.famulus.Snapshot1`)
  before executing the skill.
- `polkit_actions` — the `org.famulus.*` polkit action IDs the skill may
  invoke. Tier 0 skills MUST declare none; tier 1/2 skills MUST declare at
  least one.
- `files_touched` and `network_access` — declarative and audited, not
  sandbox-enforced in v1 (v1 limitation). Consumers SHOULD surface them in
  permission prompts and audit tooling, and MAY use them for future
  enforcement.

Consumers: famulus-agentd (tier enforcement, snapshot triggering, auditing),
famulus-skills (authoring and CI validation), and any third-party tooling that
loads or inspects Famulus skills.

## Files

- `manifest.schema.json` — JSON Schema (draft 2020-12) applied to the parsed
  YAML of a `manifest.yaml`.
- `examples/wallpaper/manifest.yaml` — tier 0 example (no polkit actions, no
  system mutation, no network).
- `examples/install-software/manifest.yaml` — tier 2 example (system
  mutation, polkit actions, network access).
- `validate_manifest.py` — CLI validator.
- `test_skill_manifest.py` — unit tests (stdlib `unittest`).
- `README.md` — this file.

## Authoring notes

- `version` MUST be a quoted YAML string. An unquoted scalar such as `1.0`
  parses as a float and is rejected with a hint to quote it.
- All eight fields are required; unknown top-level fields are rejected.

## Validate a manifest

From the repo root:

```sh
.venv/bin/python skill-manifest/validate_manifest.py skill-manifest/examples/wallpaper/manifest.yaml
.venv/bin/python skill-manifest/validate_manifest.py skill-manifest/examples/install-software/manifest.yaml
```

Exit codes: 0 = valid, 1 = validation failure, 2 = usage error. Errors go to
stderr; a one-line summary goes to stdout. `--schema PATH` selects an
alternative schema file.

## Run the tests

From the repo root:

```sh
.venv/bin/python -m unittest discover -s skill-manifest -v
```

## Stability

Frozen at tag contracts-v1. Changes require an ADR, maintainer review, and a new frozen tag; already-frozen tags are never rewritten.
