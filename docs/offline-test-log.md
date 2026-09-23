# Offline test log

Append-only. **Newest first.** One entry per release, produced by running
`docs/offline-release-test.md`. `AGENTS.md` §3, C1: a release with a failed offline test does
not ship. This file is the retained record that it ran, not a summary written after the fact.

Format per entry:

```
## <version> - <date>

**Result:** pass | fail
**Machine:** real second machine (never seen Askwell) | same-machine simulation (name why)
**Proxy counters:** permitted=<n>, refused=<n> — every refused entry named in the entry below
**Capture:** tool used, file location, what it showed
**Refusals investigated:** list, or "none recorded"
**Live connections excluded from the zero-outbound figure:** none | named, with destination
**Gaps filed:** issue links, if any
```

---

## 0.7.16 - 2026-09-23

**Result:** fail (partial — the automated half only; the gate this ticket built has not yet
had a real cold-cable run)
**Machine:** same-machine dev stack, network not physically disconnected — this is `M7-OFFLINE-TEST-145`
building the gate itself, not yet a release run against it. Real second/clean hardware is
unavailable on this build host (issues #590, #592, #598, the same gap the restore gate's own
log already carries).
**Proxy counters:** permitted=4, refused=4 at both the start and end of `scripts/verify-no-egress.sh`'s
run — unchanged, which is what the script checks for. The nonzero baseline predates this run
(prior manual testing on this dev stack, not attempted egress from anything this script did)
and is exactly why the script asserts the count does not *move*, rather than asserting it
reads zero — a real release run starts from a genuinely clean, network-disconnected machine
where zero is the correct baseline too.
**Refusals investigated:** not evaluated this run — the refused count did not change, so
nothing new appeared to investigate. A real gate run must still read every refusal per
`docs/offline-release-test.md` §4, including ones present before the run started.
**Live connections excluded from the zero-outbound figure:** none configured on this run
**Gaps filed:** none new. Issue #220 (pre-existing) is why the script's grounded-question check
verifies turn completion rather than exact text — see `docs/decisions.md`, this date. §1
(physical disconnect), §3.8 (voice) and §3.2's dump-import case were not exercised this run —
owed to the first release run against this gate, on hardware that can actually be
disconnected.
