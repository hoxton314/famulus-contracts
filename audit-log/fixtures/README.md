# C1 fixtures

These NDJSON fixtures are synthetic — the events, UUIDs, and timestamps
are invented — but every `hash` and `prev_hash` value is REAL, computed
with the reference functions in `../validate_chain.py` (never
hand-written). `valid-chain.ndjson` is a 4-record chain that verifies
cleanly (tier-0 wallpaper set, tier-1 wifi connect, tier-2 rpm-ostree
package install with snapshot_ref and deployment_before, tier-2 Bash
hook-deny with result error); `tampered-payload.ndjson` is the same chain
except record 2's `tool` field was altered after hashing, so its stored
hash no longer matches (hash-mismatch); `broken-link.ndjson` has a record
2 whose `prev_hash` does not equal record 1's `hash` while every record's
own hash is self-consistent (chain-link failure); `bad-genesis.ndjson`
has a self-consistent first record whose `prev_hash` is not 64 zeros
(genesis-rule failure).
