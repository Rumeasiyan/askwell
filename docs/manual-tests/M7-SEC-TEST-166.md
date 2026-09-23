# Manual test — M7-SEC-TEST-166, the pre-release security review

**Ticket:** `M7-SEC-TEST-166` — a structured review of every constraint (C1–C10) against its
actual enforcement point, findings recorded and fixed or accepted, before a release ships.
**Version under test:** `0.7.18`.
**Time:** 2–3 hours with a running stack and native inference up; longer if you also re-run the
CPU-bound eval suites (§4/§5 below note where this walkthrough intentionally does not).

**What is being checked.** Two documents this ticket produced — `docs/security-review.md` (the
repeatable checklist) and `docs/security-review-log.md` (this release's dated entry) — plus the
one code fix the review's own first run found and made: `api/src/askwell/websearch.py`'s
`ask_escalate_web` checked `messages.content == ""` as its abstention signal, which has been
unsatisfiable for a real abstained turn since `M2-ABSTAIN-BE-054`. This walkthrough re-derives
the log entry's own claims live rather than trusting the document — that is the entire point of
the ticket, and of this test.

**This is not a UI feature.** Nothing here is a screen. The "user" walking this path is the
maintainer running the checklist, mostly by clicking through the real app to generate real
turns and reading the results back over the API and the container logs — per the ticket's own
"UI States: None."

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env` and fill in any variable left blank (at minimum `POSTGRES_APP_PASSWORD`).

You will need native inference running for the live abstention/escalation checks in Parts C and
D — leave a terminal open running:

```
scripts/dev.sh inference
```

**You should see:** the inference bridge report it is listening, and stay running in that
terminal for the rest of this walkthrough.

---

## Cold start

### 1. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `sandbox`, `api`, `worker` reported as
started. Wait about thirty seconds, then confirm:

```
scripts/dev.sh check
```

**You should see:** every step (lint, typecheck, format, python tests) finish clean. A red
`scripts/dev.sh check` is itself a release blocker per `docs/security-review.md` §0 — stop here
and fix it before continuing, rather than reviewing a stack you already know is broken.

### 2. Open Askwell in a browser and load a corpus to ask real questions against

```
http://127.0.0.1:8000
```

**You should see:** the app loads — first-run if this is a clean install, or the composer if a
source was added before. If first-run, add at least one real document through the app's own
**Add a source** flow (click through the UI, do not call the endpoint directly) so Parts C and D
below have a real, small corpus to ask genuinely unanswerable questions against.

---

## Part A — C1: egress is refused from inside every container, and the counter is honest

### 3. Attempt an outbound request from each of `api`, `worker`, `voice`

```
podman compose exec api curl -sv https://example.com 2>&1 | tail -5
podman compose exec worker curl -sv https://example.com 2>&1 | tail -5
podman compose exec voice curl -sv https://example.com 2>&1 | tail -5
```

**You should see:** `api` and `worker` refused by the proxy — the response body names itself
(look for the proxy's own refusal text, not a generic `curl` connection error). `voice` fails
with no route at all (it is not a member of the `egress` network) — a DNS/connection failure,
not a proxy response, and that is the expected shape for that one container.

### 4. Read the honest counter

```
curl -s http://127.0.0.1:8000/network | jq
```

**You should see:** `refused` and `permitted` counters, plus a `recent` list. Note the current
`refused` count — it should be at least 2 higher than before step 3 (one for `api`, one for
`worker`), not reset to zero and not suspiciously round.

---

## Part B — C2/C3: SQL validation and sandbox isolation

### 5. Confirm the parser, not a regex, is the only path

```
grep -rn "sqlglot" api/src/askwell/sql*.py api/src/askwell/sql/*.py
grep -rn "import re" api/src/askwell/sql*.py api/src/askwell/sql/*.py
```

**You should see:** every SQL-handling file importing `sqlglot`; any `import re` hits you find
are not on the statement-validation path (read each one — confirm none of them regex-matches
raw SQL text to decide read vs. write).

### 6. Run the forbidden-shape and hostile-dump test suites

```
scripts/dev.sh test -- -k "sql_validate or dump_containment or sandbox"
```

**You should see:** all cases pass, including top-level `DELETE`/`UPDATE`/`INSERT`, a
data-modifying CTE with `RETURNING`, and the hostile-dump fixtures.

### 7. Attempt a write as the sandbox's own read-only role

Load any small `.sql` dump through the app's own **Add a source → Database dump** flow first if
you have not already got a sandboxed database, then:

```
podman compose exec sandbox psql -U askwell_sandbox_readonly -d <the sandboxed database name> \
  -c "DELETE FROM pg_catalog.pg_class WHERE relname = 'nonexistent';"
```

**You should see:** `permission denied` — refused by Postgres itself, independent of whatever
`sqlglot` would have said about the statement shape.

---

## Part C — C5: abstention happens before generation, and its trace step is real

### 8. Ask the app a question your corpus cannot answer

In the browser, in the composer, ask something with no relationship to anything you added in
step 2 — e.g. "What is the capital of a country not mentioned anywhere in my files?"

**You should see:** Askwell abstains — it says it found nothing relevant, names real
document/chunk counts (never a placeholder number), and offers to search the web. This is the
screen the rest of Part D escalates from.

### 9. Confirm the trace carries a real abstain step, not just empty text

```
curl -s http://127.0.0.1:8000/network | jq
```

Note the `message_id` shown in the browser's network tab or dev tools for the turn you just
asked (or query the conversation's messages via the app), then:

```
curl -s http://127.0.0.1:8000/ask/<that message id> | jq '.trace.steps[] | select(.kind == "abstain")'
```

**You should see:** a `{"kind": "abstain", "reason_code": "below_threshold", ...}` object — this
is the exact structural signal the C10 fix in step 12 below depends on existing.

---

## Part D — C10: web escalation is a per-question proxy grant, verified at the proxy

This is the part of the review that found and fixed a real bug (`api/src/askwell/websearch.py`).
The fix makes a genuinely abstained turn's own "search the web" button work at all — before it,
every real abstention 409'd when escalated, because the code was checking for an empty
`content` string that abstained turns have not had since `M2-ABSTAIN-BE-054`.

### 10. Ask several more unanswerable questions and decline every offer

Repeat step 8 for a handful more (aim for at least five) unanswerable questions. Each time,
**do not click "search the web"** — leave the offer alone or dismiss it.

**You should see:** each turn abstains the same way as step 8.

### 11. Confirm zero fetches happened while you declined

```
curl -s http://127.0.0.1:8000/network | jq '.permitted, .refused'
```

**You should see:** the `permitted` counter unchanged from before step 10 — declining an offer
must never itself open a grant.

### 12. Accept exactly one offer and watch it open and close

Go back to one of the abstained turns and click through the app's own **Search the web** offer
(this is the escalation that the ticket's fix in `websearch.py` makes actually succeed now — see
"Known gaps" if it still 409s on your build, which would mean the fix is not present).

**You should see:** the app proceeds to search and returns an answer with web-sourced
citations, each marked as not-your-material with a retrieval date, per C10's own requirement
that web results never enter the provenance margin as if they were your files.

### 13. Confirm exactly one grant opened and closed, at the proxy

```
curl -s http://127.0.0.1:8000/network | jq '.permitted, .refused'
```

**You should see:** `permitted` incremented by exactly the amount one search accounts for (one
or two, depending on how many hosts the search actually reaches) — not a larger jump, and no
change to `refused`.

```
podman compose exec redis redis-cli --scan --pattern 'askwell:egress:grant:*'
```

**You should see:** no keys returned — the grant that opened for step 12 is gone; it did not
outlive the turn.

### 14. Confirm the audit trail recorded exactly one open and one close

```
scripts/dev.sh psql -c "select kind, created_at from audit_decisions where kind like 'web_search_grant%' order by created_at desc limit 4;"
```

**You should see:** exactly one `web_search_grant_opened` and one `web_search_grant_closed` row
from the escalation you just accepted in step 12 — not more, not a lone `opened` with no
matching `closed`.

---

## Part E — C6: the audit chain is intact and the app role cannot rewrite it

### 15. Verify both hash chains

```
podman compose exec api askwell-verify
```

**You should see:** both chains reported intact.

### 16. Attempt to alter a record as the application's own role, not the bootstrap superuser

```
podman compose exec postgres psql -U askwell_app -d askwell \
  -c "UPDATE audit_decisions SET kind = kind WHERE id = (SELECT id FROM audit_decisions LIMIT 1);"
```

**You should see:** `permission denied for table audit_decisions` — refused by a database grant,
not by application logic. (Note: this must connect explicitly as `askwell_app`, not through
`scripts/dev.sh psql`, which connects as the Postgres bootstrap superuser and would trivially
succeed, proving nothing about what the app role can do.)

---

## Part F — C8/C9: secrets and licensing

### 17. Grep for committed secrets

```
git log --all -p -- .env | head -1
git grep -nE 'sk-[a-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN.*PRIVATE KEY'
```

**You should see:** both commands return nothing.

### 18. Regenerate the notices file and read its exit code

```
scripts/dev.sh notices
```

**You should see:** either a clean pass, or a failure naming a specific disallowed-licence
package — see "Known gaps" below for this release's actual state, which is a known, tracked red.

---

## Known gaps

- **C9 is known red on this release, by design, not by omission.** `scripts/dev.sh notices`
  fails on `phonemizer` (GPL-3.0-or-later, a transitive dependency of the `kokoro-onnx` TTS
  engine) — tracked as issue #619, and `docs/release-procedure.md` step 3b already documents it
  as a release blocker. Do not report step 18's failure as a new finding; confirm it matches
  issue #619 and move on.
- **C3's and C7's hostile-fixture suites were not re-exercised against a freshly-added live
  document or dump in the review this ticket produced**, because adding a source under
  `ASKWELL_ROOTS_MOUNT` hits a pre-existing SELinux container-traversal gap on the dev host
  (issue #107). The unit-test hostile-fixture suites (step 6 above) do not depend on that mount
  and were run instead. If your host does not hit #107, adding a hostile document/dump live and
  confirming the same flag/refusal fires is a stronger check than this walkthrough performs —
  do it if you can, but its absence here is not a defect in this ticket.
- **`grounded_qa.v1` (C4) and `abstention.v1`/`web_escalation.v1` (C5/C10) eval scores are not
  re-run by this walkthrough.** They are CPU-bound, multi-minute suites on a single generation
  slot and were only partially completed in the review session this document is based on
  (`abstention.v1` did not finish; its score is unmeasured for `0.7.18`, filed as issue #625,
  alongside `docs/BRAIN.md`'s own stale Eval baseline table). The abstain-before-generation code
  path itself (Part C above) is independent of the eval score and was verified live. Run
  `scripts/dev.sh eval --suite <name>` yourself if you have inference capacity to spare and
  record the result in `docs/security-review-log.md`.
- **No branch protection on `main`** (issue #623) — a repository-settings gap, not something
  this walkthrough or the ticket's own code changes touch. CI runs on every push but nothing
  stops a direct push or a merge past a red check.
- **A second, narrower web-escalation gap exists and is not fixed by the change under test**:
  the "no connections configured" database-override turn (`M4-RESULT-FE-111`) writes a different
  trace shape and is not recognised as escalatable by the fixed condition either — issue #624.
  If you specifically construct that state (no database connections configured, ask a question
  that would need one) and try to escalate it, expect it to still 409. That is the filed gap, not
  a new bug to report.
- **No automated dependency-vulnerability scanning runs in CI.** `pip-audit`/`pnpm audit` were
  run by hand once for this release (see `docs/security-review-log.md`'s Dependency review
  section); this walkthrough does not re-run them, since they need the built images and a
  one-off network exception. Run them yourself if auditing dependency state specifically.
