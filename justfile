# famulus-contracts — contract validation entry points.
# `just validate` is the Phase 0 gate: all validators + tests green.

set shell := ["bash", "-uc"]

python := ".venv/bin/python"

default: validate

# Bootstrap the validation virtualenv (idempotent).
venv:
    @test -x {{python}} || (python3 -m venv .venv && .venv/bin/pip install --quiet -r tools/requirements.txt)

# Run everything: meta-schema checks plus every contract's validator and tests.
validate: venv schemas c1 c2 c3 c4 c5 c6
    @echo "OK: all contract validators and tests passed."

# Every *.schema.json must pass the draft 2020-12 meta-schema.
schemas: venv
    {{python}} tools/check_schemas.py

# C1 — audit-log record schema + hash-chain verifier.
c1: venv
    {{python}} -m unittest discover -s audit-log -v
    {{python}} audit-log/validate_chain.py audit-log/fixtures/valid-chain.ndjson

# C2 — org.famulus.Agent1 / org.famulus.Conversation1 D-Bus interface.
c2: venv
    {{python}} -m unittest discover -s dbus-agent -v

# C3 — skill manifest.yaml schema + example manifests.
c3: venv
    {{python}} -m unittest discover -s skill-manifest -v
    {{python}} skill-manifest/validate_manifest.py skill-manifest/examples/wallpaper/manifest.yaml
    {{python}} skill-manifest/validate_manifest.py skill-manifest/examples/install-software/manifest.yaml

# C4 — org.famulus.Snapshot1 D-Bus interface + snapshot_ref format.
c4: venv
    {{python}} -m unittest discover -s dbus-snapshot -v

# C5 — permission/tier policy schema + shipped default policy.
c5: venv
    {{python}} -m unittest discover -s tier-policy -v
    {{python}} tier-policy/validate_policy.py tier-policy/default-policy.yaml

# C6 — Claude stream-json → D-Bus event map fixtures + reference mapper.
c6: venv
    {{python}} -m unittest discover -s event-map -v
