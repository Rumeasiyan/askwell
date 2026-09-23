# Security review — the pre-release gate

`M7-SEC-TEST-166`. Run this once per release, alongside `docs/restore-release-test.md` and
`docs/offline-release-test.md` (after `docs/release-procedure.md` step 1, before step 4).
**A failed run blocks the release** — a constraint whose enforcement point turns out to be a
convention rather than a mechanism is a release blocker, per `AGENTS.md` §3's own framing.

This document is the checklist: what to check, where its enforcement point actually lives, and
how to verify that mechanically rather than by reading the code and believing it. Results go in
`docs/security-review-log.md`, one entry per release, in the same append-only shape
`docs/restore-test-log.md` and `docs/offline-test-log.md` already use.

**What this is not.** A single-maintainer review is not equivalent to external testing —
`AGENTS.md` §3's own out-of-scope line for this ticket. No penetration testing, no third-party
audit. It is the deliberate, structured check of every constraint's own stated enforcement
point, so that the first finding against this product is the maintainer's, not an auditor's.

---

## 0. Before you start

A running stack, `scripts/dev.sh check` clean, and (for the live checks in §2 and §10) native
inference up (`scripts/dev.sh inference`, or the standing dev supervisor). Several steps need a
real Postgres session as both the application role and the bootstrap superuser — `scripts/dev.sh
psql` connects as `POSTGRES_USER` (`askwell`), which is the Postgres bootstrap/admin role the
official image always grants superuser to, **not** `askwell_app`, the restricted role the API
itself connects as. Testing a `REVOKE` against `scripts/dev.sh psql`'s own connection proves
nothing — of course a superuser can do anything. Connect explicitly as `askwell_app` (`podman
compose exec postgres psql -U askwell_app -d askwell`) to test what the application role can
actually do.

---

## 1. C1 — local by default, no outbound network calls without explicit per-unit opt-in

**Enforcement point:** the default-deny egress proxy (`api/src/askwell/egress.py`), not
application code — every container's `HTTP_PROXY`/`HTTPS_PROXY` points at it, it sits on the
only network with a route out, and in local mode it has no destination it is ever configured to
permit (`docs/architecture.md` §5).

**How to verify:**
- `docs/offline-release-test.md` in full — it already is this constraint's own dedicated gate,
  run separately per `docs/release-procedure.md` step 3a. Do not re-derive its content here;
  record only whether it passed for this release and link the entry.
- `GET /network` (with a session cookie — see §0) reports `refused`/`permitted` counters and a
  `recent` list. Confirm the counts are plausible for what actually ran in this session, not
  reset or suspiciously round.
- Attempt an outbound request from inside each of `api`, `worker` and `voice` (`podman compose
  exec <service> curl -sv https://example.com`) and confirm each is refused by the proxy, not a
  DNS failure or a timeout — the refusal body names itself (`egress.py`'s `REFUSAL_BODY`), which
  is how to tell "refused" from "the network happens to be unreachable for an unrelated reason."

## 2. C2 — model-generated SQL is never trusted; `sqlglot`, never regex

**Enforcement point:** `api/src/askwell/sql/validate.py`, parsing with `sqlglot` and rejecting
anything that is not a single `SELECT`/`WITH` read, walking the whole parsed tree rather than
trusting the top-level statement type alone — **plus**, independently, the read-only database
role (`sql_execute.py`, `askwell_sandbox_readonly` for a sandbox database, the connection's own
stored read-only credential for a live one).

**How to verify:**
- `grep -rn "sqlglot" api/src/askwell/sql*.py api/src/askwell/sql/*.py` and confirm every SQL
  path routes through it; separately, confirm no `re.match`/`re.search` against raw SQL text
  exists anywhere on the validation path (`grep -rn "import re" api/src/askwell/sql*.py
  api/src/askwell/sql/*.py` and read each hit).
- `api/tests/test_sql_validate.py`/`test_sql_validate_db.py` cover the forbidden shapes
  (top-level `DELETE`/`UPDATE`/`INSERT`, a data-modifying CTE with `RETURNING`, `SELECT ...
  INTO`, dialect-specific write functions) — run them and read the list of cases, not just the
  pass count.
- Attempt a write as the query role directly: connect as `askwell_sandbox_readonly` against a
  loaded sandbox database and run an `UPDATE`/`DELETE`/`INSERT` — must be refused by Postgres
  itself (`permission denied`), independently of whatever `sqlglot` would have said.

## 3. C3 — an imported dump is untrusted code; sandbox only, one database per source

**Enforcement point:** `api/src/askwell/sandbox.py` — a dedicated, no-egress sandbox Postgres
container, one database per source, loaded under a restricted non-superuser owner role with
`PUBLIC`'s default `CONNECT` privilege revoked, queried afterward only through
`askwell_sandbox_readonly`.

**How to verify:**
- `api/tests/test_dump_containment.py`, `test_sandbox.py` — the hostile-dump fixture suite
  (`M4-DUMP-SEC-091`). Run it against the real sandbox instance, not mocked.
- `compose.yaml`'s `sandbox` service: confirm it is not a member of the `egress` network and has
  no route to the proxy — a dump that cannot write is contained by role grants; a dump that
  could still reach the network would not be.
- Confirm `PUBLIC` connect really is revoked per-database: as the bootstrap superuser, attempt
  `\c <sandbox-db>` as a role with no explicit grant on that specific database and confirm
  refusal.

## 4. C4 — every factual claim carries a citation

**Enforcement point:** `api/src/askwell/agent/claims.py` (`segment_claims`) plus the
`grounded_qa.v1` eval suite, which scores citation correctness against the actual passage cited,
not answer text alone (`eval/grounded.py` drives a real turn through `askwell.ask`, not an
isolated completion).

**How to verify:**
- Run `scripts/dev.sh eval --suite grounded_qa.v1` against the real stack and read the citation
  score, not just the answer-quality score — they are graded separately by design.
- Ask a live question against the real corpus and open its trace: every claim should resolve to
  a specific passage; a sentence with no marker should not exist in an otherwise-cited answer.

## 5. C5 — abstention over invention

**Enforcement point:** the abstention decision is made in code, before generation —
`askwell.ask._run_generation` compares every candidate's score against
`Settings.retrieval_score_threshold` and never calls `compose()` below it — **and** measured by
the `abstention.v1` eval suite, pass bar ≥ 0.90 (`docs/build-plan.md`), worst-of-3 reported
alongside mean.

**How to verify:**
- Ask a live question the corpus cannot answer; confirm the response abstains with real
  document/passage counts (never a placeholder) and that `messages.trace` carries a
  `{"kind": "abstain"}` step with a `reason_code`.
- Run `scripts/dev.sh eval --suite abstention.v1` against the real stack. Record mean and
  worst-of-3 in the log entry — see §11's own finding on why this has not been recorded in
  `docs/BRAIN.md`'s own baseline table for some time.
- **Do not** treat `.github/workflows/eval.yml`'s CI status as this check having run — see §11.
  It is `workflow_dispatch`-only (issue #256): the suite has never executed automatically, by
  design, because no `self-hosted, askwell`-labelled runner is registered. A green check there
  means nothing; a run must be triggered and its output read.

## 6. C6 — the audit log is append-only and tamper-evident

**Enforcement point:** database grants, not application logic — `REVOKE UPDATE, DELETE,
TRUNCATE ... FROM askwell_app` on both audit tables, `GRANT SELECT, INSERT` only (migration
`20260827_a8208099ef38`), plus the hash chain `askwell-verify` checks.

**How to verify:**
- `podman compose exec api askwell-verify` — both chains, `chain intact`.
- Connect **as `askwell_app` specifically** (see §0's warning about `scripts/dev.sh psql`) and
  attempt `UPDATE audit_decisions SET ... WHERE id = (SELECT id FROM audit_decisions LIMIT
  1);` — must fail with `permission denied for table audit_decisions`, not a syntax error or
  success.
- Do not call the result "immutable" in the log entry or anywhere else — `AGENTS.md` §3 C6 is
  explicit that the honest claim is tamper-*evident*: the application never rewrites history,
  and manual tampering (by whoever owns the machine, with database superuser access) is
  detectable, not impossible.

## 7. C7 — retrieved content is data, never instruction

**Enforcement point:** `api/src/askwell/agent/compose.py` — `delimit_candidates`,
`delimit_tool_result`, `delimit_web_result` each wrap their content in an unforgeable block
(`<retrieved-content>`, `<tool-result>`, `<web-content>`), the system prompt states delimited
content is data, and `flag_injection_text` flags instruction-like patterns onto the trace.

**How to verify:**
- `api/tests/test_compose.py`, `test_tools.py`, `test_websearch.py` — run the hostile-content
  cases (`grep -l hostile api/tests/*.py`) and confirm they pass.
- Add a document containing an injection attempt ("ignore previous instructions and ...") to the
  real corpus, ask a question that retrieves it, and confirm the trace flags it — the model
  answering the actual question, not obeying the embedded instruction, is the pass condition.
- Repeat with a *web page* fixture carrying the same attempt (`M6.5`'s `<web-content>` path).
  Confirm the same flagging fires — and record in the log that the mitigation is **weaker for
  web content than for documents**: the user chose their documents and did not choose a page
  written to contain instructions (`docs/web-search.md` §5). This is a residual risk to name
  honestly, not a defect to mark fixed.

## 8. C8 — secrets are environment variables, never committed

**Enforcement point:** `.gitignore` (`.env`, `.env.*`, `!.env.example`) plus review — there is no
mechanical scanner in this repository today (see §11).

**How to verify:**
- `git log --all -p -- .env` (and any other real env file) — must return nothing.
- `git grep` for plausible secret shapes (`sk-[a-z0-9]{20,}`, `AKIA[0-9A-Z]{16}`, a PEM private
  key header) across the tracked tree.
- `podman compose logs` across every service, grepped for `password`/`secret`/`token=`/
  `api_key`, filtered for the known placeholder strings in `.env.example` — anything left over
  is a real finding.
- `.env.example` must already declare every variable `.env` needs, in the same change that
  introduced it — spot-check a recent ticket that added a credential.

## 9. C9 — a bundled model's licence permits redistribution and commercial use, ungated

**Enforcement point:** `scripts/dev.sh notices` (`scripts/generate_notices.py`,
`api/src/askwell/notices.py`) — regenerates `NOTICES.md` from what is actually installed and
fails on a disallowed licence (strong copyleft, non-commercial, no-derivatives, unlicensed),
wired as `docs/release-procedure.md` step 3b.

**How to verify:**
- Run `scripts/dev.sh notices` and read its exit code, not just whether `NOTICES.md` changed.
- For each of the seven bundled model roles in `askwell.notices`'s own static table, confirm the
  licence and gating status against the model's actual registry entry (`AGENTS.md` §4) —
  do not trust a name written down previously without re-checking.

## 10. C10 — web search is a per-question escalation, never an automatic fallback

**Enforcement point:** the proxy grant, not the answer path — `askwell.egress.open_grant`/
`close_grant`, called from exactly one place (`askwell.websearch.escalate_web_search`), scoped
to one turn's `message_id`, with both a hard Redis TTL (`web_search_grant_ttl_seconds`) and a
`try`/`finally` close covering every return path including cancellation. `POST
/ask/{message_id}/escalate/web` is the only HTTP route that can ever reach it, and it refuses a
turn that did not abstain or answer partially.

**How to verify — at the proxy, not from application code, per `AGENTS.md`'s own framing for
this constraint:**
1. Ask twenty questions the real corpus cannot answer. Decline every offer. Read `GET /network`'s
   `refused`/`permitted` counters before and after — **zero** new `permitted` entries, and no
   `web_search`-shaped destination in `recent`.
2. Accept exactly one offer (`POST /ask/{message_id}/escalate/web`). Confirm in the same window:
   exactly one `web_search_grant_opened` and one `web_search_grant_closed` decisions record
   (`audit_decisions`, `kind` column), and `permitted` incremented by the expected amount for
   that one search — not more.
3. Confirm the grant closes with the turn even on a provider failure or a cancelled search —
   `api/tests/test_egress.py`'s `test_closing_a_grant_removes_it` and
   `test_two_escalations_hold_two_independent_grants` cover this structurally; a live run should
   still show the grant absent from Redis (`redis-cli --scan --pattern 'askwell:egress:grant:*'`)
   once the turn completes.
4. State the negative explicitly in the log entry: no code path can initiate a fetch without an
   explicit per-question authorisation, because the proxy itself has no permitted destination
   until a grant naming one exists, and the one function that can create a grant is reachable
   from exactly one authenticated, per-turn HTTP route.
5. Name the same residual risk C7 names, specific to web content: the injection mitigation
   applies identically to fetched pages, but is weaker there for the reason given in §7 —
   `docs/web-search.md` §5.

## 11. Dependency vulnerability review

No automated scanner runs in CI today — this is a manual step until one is added.

- **Python:** `pip-audit -r <(uv export --no-hashes --no-dev)` inside the built `api` image
  (needs network — a deliberate, one-off exception to the "no egress in the dev toolchain" rule,
  the same shape `scripts/dev.sh lock`/`web-install` already carve out).
- **JavaScript:** `pnpm audit --prod` inside the built `web` image, same network exception.
- A finding with no fix available is assessed for actual reachability, not reacted to by
  severity alone — e.g. a vulnerable transitive dependency of a build-time-only tool that never
  ships, or a runtime dependency gated behind a code path this product never exercises
  (`next.config.ts`'s `images.unoptimized: true` meaning `next/image` never calls into `sharp`
  at all, which is exactly the reasoning that applied to the `sharp` finding this review fixed
  outright rather than merely noted — see the log entry).

## 12. Cross-cutting: is the enforcement point a mechanism or a convention?

For every constraint above, ask the question `AGENTS.md` itself poses: if the enforcement point
turns out to be "the code currently does this" rather than something that fails loudly when
bypassed, that is a release blocker, not a note. Specifically check:

- Whether `main` has branch protection requiring the checks each constraint leans on — a CI job
  that would fail is not an enforcement point if nothing stops a merge past it.
- Whether the constraint's own eval/test suite has actually been run recently against the real
  stack, versus assumed current because a ticket once ran it.
