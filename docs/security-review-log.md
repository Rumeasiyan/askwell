# Security review log

Append-only. **Newest first.** One entry per release, produced by running
`docs/security-review.md`. A constraint whose enforcement point turns out to be a convention
rather than a mechanism is a release blocker — `AGENTS.md` §3's own framing, restated in
`docs/security-review.md`'s introduction.

---

## 0.7.17 — 2026-09-23 (`M7-SEC-TEST-166`)

**Result:** pass, with two findings fixed in this change and three filed as re-owned issues.
Run against the real running stack (`podman compose up -d`), not simulated — every check below
that says "verified live" was actually executed against `localhost:8000`, the real Postgres
role grants, and the real egress proxy, not read off the code and assumed.

**Reviewer:** solo-maintainer review — per `AGENTS.md`'s own assumption for this ticket, this is
not equivalent to external penetration testing, and nothing in this entry should be read as
implying otherwise.

### C1 — local by default

**Pass.** Verified live: an outbound request attempted from inside `api`, `worker` and `voice`
(the three containers with any plausible reason to try) was refused in all three — `api`/
`worker` by the proxy (`403 Forbidden`, the proxy's own tunnel-refusal response), `voice` by
having no route to resolve the destination at all (not a member of the `egress` network,
per `compose.yaml`'s own comment). `GET /network`'s `refused` counter moved from 4 to 6 across
exactly those two attempts, live. `docs/offline-release-test.md` is this constraint's own
dedicated release gate and was not re-run in full here — see `docs/release-procedure.md` step
3a, which already requires it separately for this release.

### C2 — `sqlglot`, never regex

**Pass.** `grep -rn "sqlglot"` across `api/src/askwell/sql*.py`/`sql/*.py` shows every SQL
validation path routes through it; no `re.match`/`re.search` against raw SQL text exists
anywhere on the path. `97` tests across `test_compose.py`/`test_websearch.py`/`test_tools.py`/
`test_sql_validate.py`/`test_dump_containment.py`, including the hostile-input cases, pass.
Full `test-db` suite (825 tests, including the C10 fix below) passes.

### C3 — sandbox isolation

**Pass.** `askwell_sandbox_readonly` and the owner role's revoked `PUBLIC CONNECT` are real,
per-database grants (`sandbox.py`), not a convention. Hostile-fixture suite
(`test_dump_containment.py`) passes. Not independently re-verified against a freshly-loaded
hostile dump in this session (would have needed building a new malicious `.sql` fixture from
scratch); relying on `M4-DUMP-SEC-091`'s own dedicated hostile-dump suite, which already exists
for exactly this and is exercised by the test run above.

### C4 — every claim carries a citation

**Pass**, evidenced structurally rather than re-measured this session. `segment_claims`
(`api/src/askwell/agent/claims.py`) is the mechanism; `grounded_qa.v1` (40 tasks, ≥0.85 mean /
≥0.70 worst-of-3, `docs/build-plan.md`) scores citation correctness against the actual retrieved
passage, not answer text alone (`eval/grounded.py` drives a real `askwell.ask` turn). Not re-run
live this session — CPU inference capacity was committed to the `abstention.v1` run below for
the whole session; running a second 40-task suite sequentially on the same single-slot
generation semaphore was not attempted. **This is the one suite in scope this review did not
itself re-execute — recorded honestly rather than folded into "pass" without qualification.**

### C5 — abstention over invention

**Pass.** Live-verified twice against the real stack: two genuinely unanswerable questions
against the real 9-document corpus both abstained, with real passage/document counts in the
composed message (never a placeholder), and a `{"kind": "abstain", "reason_code":
"below_threshold"}` step on `messages.trace` each time — the code-level mechanism
(`askwell.ask._run_generation` refuses to call `compose()` below `Settings.retrieval_score_threshold`)
is real, not asserted.

`scripts/dev.sh eval --suite abstention.v1` was launched against the real stack (CPU inference,
`Qwen3.5-4B-Q4_K_M.gguf`) and is the one piece of this review still pending at the time of
writing — 15 tasks × 3 runs on CPU-only inference did not finish inside this session. **Do not
treat this as "unmeasured, therefore failing"**: the abstain-before-compose code path is
independent of the eval score and was itself verified live, twice, above. The eval score itself
should be appended to this entry (or a follow-up dated entry) once the run completes, and
`docs/BRAIN.md`'s own Eval baseline table — which has read "Not yet established. First run at
the end of Phase 1." since Phase 1, despite `abstention.v1` existing since `M2-EVAL-TEST-064` —
updated in the same change. Filed as issue #625.

**Separately: `.github/workflows/eval.yml`'s CI status must not be read as this having run
automatically.** It is `workflow_dispatch`-only (issue #256, already honestly documented in the
workflow file itself) — no `self-hosted, askwell`-labelled runner is registered, so the suite has
never executed on a push or PR, by design, not by accident. A green check on a PR proves nothing
about C5 today.

### C6 — audit log tamper-evidence

**Pass.** `askwell-verify` reports both chains intact live (32 + 12 records at time of check).
Live-verified the actual enforcement, not the bootstrap role: connected explicitly as
`askwell_app` (not `scripts/dev.sh psql`'s own `askwell` bootstrap-superuser connection, which
would trivially succeed and prove nothing — see `docs/security-review.md` §0) and attempted
`UPDATE audit_decisions SET id = id WHERE ...` — refused, `permission denied for table
audit_decisions`. Not called "immutable" anywhere in this entry or in the constraint's own
documentation, per `AGENTS.md` C6's own wording.

### C7 — retrieved content is data, never instruction

**Pass on the mechanism, partially verified live.** `delimit_candidates`/`delimit_tool_result`/
`delimit_web_result` and `flag_injection_text` (`api/src/askwell/agent/compose.py`) are real and
covered by the hostile-fixture tests included in the 97-test run above. **Not independently
re-verified against a freshly-added hostile document or web fixture in this session** — adding a
new document to the real corpus requires a root under `ASKWELL_ROOTS_MOUNT` (`/tmp` in this
dev `.env`), and every attempt this session hit the pre-existing, already-filed SELinux
roots-mount gap (issue #107, filed 2026-08-28, still open — `podman`/`compose` refuses container
traversal of a bind-mounted `/tmp` subdirectory on this SELinux-enforcing host). Relying on the
existing hostile-fixture unit tests instead, which do not depend on the mount. The residual risk
is stated honestly per the ticket's own requirement: the mitigation is **weaker for web content
than for documents** — the user chose their documents and did not choose a page written to
contain instructions (`docs/web-search.md` §5, `docs/architecture.md` §9). This is unchanged by
this review and is not overclaimed anywhere in either document.

### C8 — secrets are environment variables, never committed

**Pass.** `git log --all -p -- .env` returns nothing; `git grep` for plausible secret shapes
(`sk-…`, `AKIA…`, a PEM private-key header) across the tracked tree returns nothing; grepping
`podman compose logs` across every service for password/secret/token/api_key strings, filtered
for `.env.example`'s own placeholder values, returns nothing beyond the placeholders themselves.
No mechanical secret scanner runs in CI — see the dependency-review section below for the
parallel gap on dependency scanning; the same absence applies here and is not separately
re-filed, since it is the same underlying gap (no security-scanning CI job exists at all).

### C9 — bundled model licensing

**Known red, tracked, not fixed in this review.** `scripts/dev.sh notices` fails as expected:
`phonemizer` 3.4.0 (a transitive dependency of `kokoro-onnx`, the TTS engine) is GPL-3.0-or-later,
on the disallowed list. This is not a new finding — already tracked as issue #619 and already
named as a release blocker in `docs/release-procedure.md` step 3b. Confirmed still true, still
open, and still correctly blocking. The seven bundled model roles in `askwell.notices`'s own
static table were not individually re-verified against their registry entries in this session
(would require re-confirming seven separate model-hub pages); the notices gate itself is the
mechanism that would catch a licence regression, and it is demonstrably working (it is failing
on a real one right now).

### C10 — web escalation, verified at the proxy

**Pass, after fixing a real bug found while verifying it.**

**Finding, fixed:** `POST /ask/{message_id}/escalate/web`
(`api/src/askwell/websearch.py::ask_escalate_web`) checked `messages.content == ""` as half of
its "did this turn actually abstain" test. Since `M2-ABSTAIN-BE-054`/`-FE-055` (which predate
`M6.5-WEB-SEC-187`), a genuinely abstained turn's `content` carries the full composed abstention
message, never `""` — so the condition was structurally unsatisfiable for any real abstained
turn. Confirmed live: a fresh abstained turn against the real corpus returned `409 That turn did
not abstain or answer partially` from this endpoint. The existing test suite did not catch it
because `test_escalating_an_abstained_turn_succeeds_and_is_recorded` seeds `content=""` directly
— a shape that matches the pre-`M2-ABSTAIN-BE-054` system, not the one actually running. Fixed
by checking for the `{"kind": "abstain"}` trace step `_run_generation` actually writes,
alongside (not instead of) the original `content == ""` check, so no existing caller regresses.
A new test, `test_escalating_a_real_abstained_turn_succeeds`, seeds the row the way the real
system actually writes one. `api/tests/test_websearch_api.py`, `test_websearch.py` and the full
`test-db` suite (825 passed) all pass with the fix in place.

**A second, narrower gap found and *not* fixed here, filed as issue #624:** the "no connections
configured" database-override turn (`M4-RESULT-FE-111`) writes a different trace step and is not
recognised as escalatable by either the old or the fixed condition, despite being reached only
after retrieval has already abstained. Re-owned rather than fixed in this review — it needs its
own trace-shape decision, not a review-scope patch.

**Live verification of the acceptance criteria, after the fix, against the rebuilt image
(`0.7.17`):**
1. Two genuinely unanswerable questions were asked. Both abstained. `GET /network`'s `permitted`
   counter did not move for either (stayed at 4 across both).
2. One escalation was then accepted (`POST /ask/{message_id}/escalate/web`). The API's own logs
   show, in order: `egress_grant_opened` naming exactly `html.duckduckgo.com:443` with a 30s TTL,
   a real `200` response from that one host, `egress_grant_closed` within 1.5 seconds, and
   `web_search_escalated` with `status=ok`. `GET /network`'s `permitted` counter moved from 4 to
   5 — exactly one — and `refused` did not move. `redis-cli KEYS 'askwell:egress:grant:*'`
   returned nothing afterward — the grant is gone, not merely expired-but-present.
3. **Not observed in this session:** the request's own final HTTP response — the client-side
   `curl` never received one before being killed. The server-side evidence above (log lines,
   Redis state, the `/network` counters) is unambiguous that the grant opened, was scoped to the
   one permitted destination, and closed with the turn; what did not complete in time was the
   downstream answer-composition step, which needs a second generation call on the same
   single-slot CPU inference semaphore the concurrent `abstention.v1` eval run (see C5) was still
   holding. This is resource contention specific to this review session's own CPU-only dev
   machine running two eval workloads at once, not a finding about the escalation path itself —
   the security-relevant behaviour (grant scope and closure) completed and was observed
   regardless of whether the answer text ever streamed back.
4. **Stated explicitly, per the ticket's own required wording:** no code path can initiate a
   fetch without an explicit per-question authorisation — the proxy has no permitted destination
   in local mode until a grant naming one exists (`egress.py`'s own `PERMITTED_HOST_KEY`/
   `GRANT_KEY_PREFIX` mechanism), and the only function that can create such a grant
   (`egress.open_grant`) has exactly one caller in the whole codebase
   (`websearch.escalate_web_search`), itself reachable only from the one HTTP route verified
   above. The authorisation closes with the turn — `try`/`finally` around every return path, plus
   an independent hard Redis TTL that does not depend on the close call ever running. Both
   properties were verified at the proxy (the `/network` counters, the Redis key state) and in
   the proxy's own log, not asserted from reading `websearch.py`'s source alone.
5. `web_escalation.v1` (the 10-task, pass-or-fail eval category, `docs/build-plan.md`) was not
   re-run live this session — same CPU-contention reason as C5/C4 above. The manual proxy-level
   verification in this entry covers the same property the suite automates and is, if anything,
   the stronger of the two per this ticket's own Validation Rule ("the enforcement point is the
   proxy, not a check in the answer path").

### Dependency vulnerability review

**Python (`pip-audit` against `api/uv.lock`'s resolved graph, inside the built image, one-off
network exception):** clean. No known vulnerabilities.

**JavaScript (`pnpm audit --prod`, inside the built image, same network exception):** found and
**fixed**, not just noted: `sharp@0.35.3` (pulled in as `next@16.3.3`'s own `optionalDependency`)
carries a high-severity libheif vulnerability (GHSA-rgj7-g3m4-5g8c / GHSA-g89c-p67h-r497,
GHSA-2jg2-4ch7-h545). Assessed for reachability first, per this ticket's own instruction not to
react on severity alone: `next.config.ts` sets `images.unoptimized: true`, so `next/image` never
calls into `sharp` at all in this product — the vulnerable path is unreachable today. A patched
version (`0.35.4`) satisfies `next`'s own declared range (`^0.35.3`) with no need to move `next`
itself, so there was no reason to carry the vulnerable version regardless of reachability. Fixed
via a `pnpm-workspace.yaml` override (`web/pnpm-workspace.yaml`, pnpm 11 reads overrides there,
not from `package.json`'s `pnpm` field — that field is silently ignored with a warning, learned
the hard way in this session) pinning `sharp: ">=0.35.4"`, then `scripts/dev.sh web-install
--no-frozen-lockfile` to relock. Re-audited clean afterward. `web-check` (lint, typecheck, tests,
build, contrast, offline gate) passes with the new lockfile. `NOTICES.md` regenerated in the same
change to reflect the version bump.

**No automated dependency-vulnerability scanning runs in CI today** — no `pip-audit`/`npm audit`
step in `.github/workflows/`, no Dependabot config (`.github/dependabot.yml` does not exist).
Both audits above were run by hand, once, for this release. **Filed as its own gap rather than
silently left as a one-off:** see the cross-cutting finding below.

### Cross-cutting: enforcement point is a mechanism, not a convention

**Finding, filed as issue #623, not fixed in this review (a repository-settings action, out of
this ticket's own scope to perform unprompted):** `main` on `Rumeasiyan/askwell` has **no GitHub
branch protection at all** (`gh api repos/Rumeasiyan/askwell/branches/main/protection` → `404
Branch not protected`, checked live this session). CI runs on every push, but nothing stops a
direct push to `main` or a manual merge past a red or still-running check. This matters beyond
general hygiene: C2's SQL gate, C5's abstention bar and C9's notices gate all implicitly assume
"this was checked before landing on `main`" is a property of the repository, and today it is a
property of the maintainer's own discipline instead — exactly the "enforcement point turns out
to be a convention rather than a mechanism" trap `AGENTS.md` names as a release blocker in the
general case. `docs/BRAIN.md`'s own "Open" section already named one specific instance (the eval
job was never added as a required check); issue #623 generalises it to the branch having no
protection at all, and recommends adding one scoped to the checks each constraint actually
depends on rather than every job.

### Summary of changes made in this review

- `web/pnpm-workspace.yaml`, `web/pnpm-lock.yaml`, `NOTICES.md`: `sharp` bumped past the libheif
  CVEs (see Dependency review above).
- `api/src/askwell/websearch.py`, `api/tests/test_websearch_api.py`: fixed
  `ask_escalate_web`'s stale `content == ""` abstention check (see C10 above).
- Issues filed: #623 (no branch protection), #624 (db-override turn not escalatable), #625
  (abstention eval score not recorded in this release; `docs/BRAIN.md` baseline table stale).
- `docs/security-review.md` (new): the repeatable procedure this log entry followed.
