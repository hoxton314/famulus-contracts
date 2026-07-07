# C4 — org.famulus.Snapshot1 (dbus-snapshot)

Contract C4 defines the D-Bus snapshot API of Famulus: the interface a
privileged snapshot service exposes so that btrfs snapshots of managed
subvolumes (`etc`, `var`) can be taken before any AI-initiated system
mutation and restored on rollback.

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT",
"SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this
document are to be interpreted as described in RFC 2119.

## Consumers

- **famulus-agentd** (session daemon) is the primary caller: it invokes
  `Create` before a mutation and records the returned `snapshot_ref` in
  the C1 audit log; it invokes `Restore` on rollback.
- **The snapshot service implementation** (system daemon) implements this
  interface on the **system bus** — snapshotting is privileged. Bus name
  `org.famulus.Snapshot1`, object path `/org/famulus/Snapshot1`,
  interface `org.famulus.Snapshot1`.
- **C1 (audit-log)** stores the `snapshot_ref` and the deployment digest;
  any audit tooling that resolves refs consumes this contract too.

## Files

| File | Purpose |
| --- | --- |
| `org.famulus.Snapshot1.xml` | D-Bus introspection XML (the machine-readable interface definition) |
| `snapshot-ref.schema.json` | JSON Schema (draft 2020-12) for the `snapshot_ref` string format |
| `validate_snapshot_contract.py` | Validator: checks the contract files and, optionally, candidate `snapshot_ref` strings |
| `test_introspection.py` | Contract lock tests (stdlib `unittest`) |
| `README.md` | This normative specification |

## Running the validator and tests

From the repository root:

```sh
# Validate the contract files themselves:
.venv/bin/python dbus-snapshot/validate_snapshot_contract.py

# Additionally validate one or more candidate snapshot_ref strings:
.venv/bin/python dbus-snapshot/validate_snapshot_contract.py \
  'famulus-snap/019811a2-7c3e-7d10-9b8a-3f2e1d0c4b5a/etc+var@1751884800'

# Run the contract tests:
.venv/bin/python -m unittest discover -s dbus-snapshot -v
```

The validator exits 0 on success, 1 on validation failure, 2 on usage
error.

## Interface summary

| Method | Signature | Purpose |
| --- | --- | --- |
| `Create` | `(in as subvolumes, in s tag) -> (out s snapshot_ref)` | Snapshot a set of subvolumes as one unit |
| `Restore` | `(in s snapshot_ref) -> (out b success)` | Restore every subvolume in a set, all-or-nothing |
| `List` | `() -> (out aa{sv} snapshots)` | Enumerate snapshot sets and their metadata |
| `Prune` | `(in u keep_last) -> (out u pruned_count)` | Delete all but the newest `keep_last` sets |

## snapshot_ref format

```
famulus-snap/<event_id>/<subvols>@<unix_ts>
```

- `<event_id>` — the lowercase UUIDv7 of the C1 audit event that
  triggered the snapshot.
- `<subvols>` — one or more btrfs subvolume names (each matching
  `[a-z0-9._-]+`) joined by `+` in the order passed to `Create`.
- `<unix_ts>` — integer seconds since the Unix epoch at creation time.

Full anchored regex (also in `snapshot-ref.schema.json`):

```
^famulus-snap/[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/[a-z0-9._-]+(\+[a-z0-9._-]+)*@[0-9]+$
```

Worked example:

```
famulus-snap/019811a2-7c3e-7d10-9b8a-3f2e1d0c4b5a/etc+var@1751884800
```

This ref names one snapshot set: audit event
`019811a2-7c3e-7d10-9b8a-3f2e1d0c4b5a` triggered snapshots of the `etc`
and `var` subvolumes (in that order) at Unix time `1751884800`
(2026-07-07T10:40:00Z).

**Design rationale — one ref per Create call.** One `Create` call
covering multiple subvolumes yields ONE ref whose `<subvols>` component
is the `+`-joined ordered list (e.g. `etc+var`), because one C1 audit
event records exactly ONE `snapshot_ref`. The individual btrfs snapshots
derived from a ref are named `<subvol>@<unix_ts>` per subvolume (here:
`etc@1751884800` and `var@1751884800`). A snapshot set MUST be treated
as a unit: it is created, restored, listed, and pruned as a whole.

## Create

`Create(as subvolumes, s tag) -> (s snapshot_ref)`

- `subvolumes` is an ordered, non-empty list of managed btrfs subvolume
  names, e.g. `["etc", "var"]`. Each name MUST match `[a-z0-9._-]+`.
- `Create` MUST create a **read-only** btrfs snapshot of each named
  subvolume.
- `Create` MUST reject unknown or unmanaged subvolume names with the
  D-Bus error `org.famulus.Snapshot1.Error.UnknownSubvolume`.
- Create MUST record the rpm-ostree deployment digest active at snapshot
  time in the snapshot metadata, and List MUST return it as
  `deployment_digest`.
- `Create` MUST return a `snapshot_ref` matching the shared regex above,
  with `<subvols>` joined in the order given in `subvolumes`.

### The tag argument (ADR-4 v1 decision)

`tag` MUST be the C1 audit `event_id` (a lowercase UUIDv7) optionally
followed by `.` and a free-form suffix. The suffix, when present, MUST
match `[A-Za-z0-9._-]{1,64}`. Full anchored form:

```
^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(\.[A-Za-z0-9._-]{1,64})?$
```

The service MUST extract the leading UUIDv7 part of `tag` and embed it
as the `<event_id>` component of the returned `snapshot_ref`; the full
`tag` (including any suffix) is stored in the snapshot metadata and
returned by `List`. A `tag` that does not begin with a lowercase UUIDv7
MUST be rejected with the D-Bus error
`org.famulus.Snapshot1.Error.InvalidTag`.

Example:

```
Create(["etc", "var"], "019811a2-7c3e-7d10-9b8a-3f2e1d0c4b5a.pre-flatpak-install")
  -> "famulus-snap/019811a2-7c3e-7d10-9b8a-3f2e1d0c4b5a/etc+var@1751884800"
```

This is an ADR-4 v1 decision: alternatives (a separate `event_id`
argument; the service allocating its own id) were rejected so that the
signature stays `(as, s)` while the ref still deterministically embeds
the triggering audit event.

### Call flow

Ordering between famulus-agentd, Snapshot1, and the C1 audit log:

1. famulus-agentd allocates the C1 audit `event_id` (UUIDv7) for the
   pending mutation.
2. famulus-agentd calls `Create(subvolumes, tag=event_id)` (optionally
   with a `.suffix`).
3. famulus-agentd writes the returned `snapshot_ref` into the C1 audit
   record for that `event_id`, alongside the deployment digest
   (`deployment_before`), and only then proceeds with the mutation.

The `event_id` therefore exists before the snapshot, and the audit
record is completed after `Create` returns.

## Restore

`Restore(s snapshot_ref) -> (b success)`

- Accepts a full `snapshot_ref`.
- `Restore` MUST restore EVERY subvolume in the set as an all-or-nothing
  attempt; it MUST NOT leave a partially restored system on failure.
- Returns `true` on success.
- Returns `false` ONLY when the restore was attempted and cleanly rolled
  back to the pre-restore state.
- MUST raise `org.famulus.Snapshot1.Error.NotFound` for an unknown ref.
- MUST raise `org.famulus.Snapshot1.Error.Busy` if another restore is in
  flight.
- A reboot MAY be required for the restore to take full effect:
  snapshots swap at the btrfs subvolume level, and processes holding the
  old subvolume mounted keep seeing pre-restore content until remount or
  reboot.

## List

`List() -> (aa{sv} snapshots)`

Each entry describes one snapshot set. The following keys are REQUIRED,
with the given D-Bus variant types:

| Key | D-Bus type | Meaning |
| --- | --- | --- |
| `snapshot_ref` | `s` | The full ref, matching the shared regex |
| `event_id` | `s` | The UUIDv7 extracted from `tag` at Create time |
| `subvolumes` | `as` | Ordered subvolume names in the set |
| `tag` | `s` | The full `tag` string as passed to `Create` |
| `created_unix` | `t` | Creation time, integer seconds since the Unix epoch |
| `deployment_digest` | `s` | rpm-ostree deployment digest recorded at Create time |

Producers MAY add extra keys; consumers MUST tolerate unknown extra keys.
The `a{sv}` dictionary is open by design — this is the ONE deliberately
open shape in this contract; every other shape in C4 is closed and
locked by the introspection XML and the schema.

### Deployment digest format

`deployment_digest` is an opaque non-empty string. In practice it is an
ostree commit checksum (64 lowercase hex characters) or a bootc image
digest of the form `sha256:<hex>`. Consumers MUST NOT parse it beyond
non-emptiness; the contract deliberately does not over-constrain it.

## Prune

`Prune(u keep_last) -> (u pruned_count)`

- Keeps the newest `keep_last` snapshot SETS, ordered by `created_unix`,
  and MUST delete all other sets (every per-subvolume snapshot in each
  pruned set).
- Returns the number of sets pruned.
- Snapshot sets referenced by a C1 audit record are still prunable: the
  audit log outlives its snapshots. An audit record whose
  `snapshot_ref` no longer resolves remains valid evidence that a
  snapshot was taken; it simply can no longer be restored.

## Errors

| Error name | Raised by | Meaning |
| --- | --- | --- |
| `org.famulus.Snapshot1.Error.UnknownSubvolume` | `Create` | A requested subvolume is not managed by the service |
| `org.famulus.Snapshot1.Error.InvalidTag` | `Create` | `tag` does not begin with a lowercase UUIDv7 |
| `org.famulus.Snapshot1.Error.NotFound` | `Restore` | The `snapshot_ref` does not name an existing set |
| `org.famulus.Snapshot1.Error.Busy` | `Restore` | Another restore is already in flight |

## Stability

Frozen at tag contracts-v1. Changes require an ADR, maintainer review,
and a new frozen tag; already-frozen tags are never rewritten.
