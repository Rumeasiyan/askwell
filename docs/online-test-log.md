# Online-mode test log

Append-only. **Newest first.** One entry per release, produced by running
`docs/online-release-test.md` (gate G13 in `docs/release-checklist.md`). `AGENTS.md` §3, C1: a
release whose online-mode test failed, or could not run, does not ship. This file is the
retained record that it ran, not a summary written after the fact.

Format per entry:

```
## <version> - <date>

**Result:** pass | fail | blocked
**Authorised destination:** <host:port>, and the addresses it resolved to in §1
**Script:** `scripts/verify-online-egress.sh` exit code, and every line that was not `pass`
**Proxy counters:** permitted <before> → <after>, refused <before> → <after>; per-conversation counts
**Capture:** tool used, where it ran, file location; SNI values seen; DNS names queried; TLS sessions to the provider vs online questions asked
**Stop on switch-off:** time from the click to the last provider packet (§4.7)
**Refusals investigated:** each one named (service, destination, why), or "only the script's own probes"
**Gaps filed:** issue links, if any
```

---

## 0.7.45 - 2026-09-25

**Result:** blocked. #737 refuses every online send, so §4.3 cannot run. This entry is the gate
being built (`M8-ONLINE-TEST-176`), not a release run against it.
**Authorised destination:** `api.openai.com:443`, stored with a placeholder key
(`sk-release-test-…`, not a real key) on the development stack, and removed after the run.
The proxy resolved it to `162.159.140.245`. §1 was not run by hand.
**Script:** exit `2`. Every check passed except step 4, which printed `BLOCKED` with the `409`
*"What online AI would send has not been decided yet …"*. That passed: one authorisation
standing, for that conversation and that destination; `api` and `worker` refused with `403`
when asking for it with no credential; `api` could not resolve the name nor reach the address
directly; the sandbox had no route to the proxy, the name or the address, and could not resolve
the name; the local conversation's question moved nothing; switching off left no authorisation,
and the next question in that conversation moved nothing.
**Proxy counters:** permitted 15 → 15, refused 11 → 13. The two new refusals are the script's own
probes. The baseline is from earlier development testing on this stack.
**Capture:** none. This host has no second machine (issues #590, #592, #598), and the positive
half cannot send anything to capture. Owed to the first release run after #737 and #730 land.
**Stop on switch-off:** not measurable: nothing was sent.
**Refusals investigated:** the two new ones are the script's own probes. The earlier entries in
`GET /network` `recent` predate this run. The `redis:6379` refusals from `api` are the deliberate
probes in `docs/manual-tests/M8-ONLINE-SEC-169.md` (its `CONNECT redis:6379` step; the proxy's
log has the one since its last restart, 2026-09-24 16:36 UTC). The `example.com:443` and
`html.duckduckgo.com:443` ones were not traced here. A release run starts from a clean install,
so its baseline is its own.
**Gaps filed:** none new. #737 (and #730 before it) blocks the positive half.
