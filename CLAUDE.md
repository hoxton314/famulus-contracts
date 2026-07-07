# famulus-contracts

Famulus is an open-source (AGPL-3.0), non-profit, AI-native atomic Linux distribution: a bootc/OCI image based on Fedora Atomic with GNOME/Wayland. Its defining feature is a GTK4/libadwaita chat app plus a thin GNOME Shell panel that wrap the UNMODIFIED official `claude` CLI (headless stream-json mode), with system control via curated MCP servers and SKILL.md skills, polkit permission tiers, snapshot-before-mutate rollback, and a hash-chained audit log. Users bring their own Anthropic subscription or API key. We never reimplement or spoof the Claude API client — we only supervise the official CLI binary.

## This repo

This repo is the single source of truth for the six Famulus interface contracts C1–C6 that bind every other repo together: JSON Schemas, D-Bus introspection XML, YAML manifest/policy shapes, and the Claude stream-json → D-Bus event map. Contracts are versioned and released as frozen git tags; all other repos build against tag `contracts-v1`. It is deliberately licensed Apache-2.0 (permissive) so that anyone — including third-party tools — can implement the contracts without copyleft obligations.

What does NOT belong here:

- Application code or implementations of any kind (no daemon logic, no GUI, no skills, no image tooling).
- Governance documents, ADRs about the wider system, or the master plan — those live in famulus-meta.
- Anything runtime: this repo ships definitions, examples/fixtures, and validation tooling for the contracts themselves — nothing else.

## Hard rules

- Work only on your assigned branch, never push to main. Open a PR when done.
- All interface shapes come from famulus-contracts — never invent your own schema.
- Run the validation steps from your task brief before opening the PR.
- Sign off commits (DCO: `git commit -s`).

## Interface contracts

All cross-repo interface shapes are defined in famulus-contracts and are frozen at tag `contracts-v1` in famulus-contracts. Build against that tag; never invent your own schema.

- **C1** — audit-log schema
- **C2** — `org.famulus.Agent1` D-Bus interface
- **C3** — skill `manifest.yaml`
- **C4** — `org.famulus.Snapshot1` snapshot API
- **C5** — permission/tier policy
- **C6** — Claude stream-json → D-Bus event map

## Coding standards

- JSON Schema (draft 2020-12) for data schemas (C1, C6).
- D-Bus introspection XML for interface definitions (C2, C4).
- YAML for manifest and policy shapes (C3, C5), each accompanied by a JSON Schema.
- Markdown for prose specifications.
- Contract-validation tooling (when added): Python 3.12+ or POSIX shell, kept minimal.

Special note: this repo IS the origin of the contracts. Here, "never invent your own schema" means: contract changes go through an ADR and maintainer review, land on main via PR, and are released as a NEW frozen tag. Never rewrite an already-frozen tag such as `contracts-v1`.
