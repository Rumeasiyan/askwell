# Manual test — M1-CITE-TEST-045, the uncited-claim query

**Ticket:** `M1-CITE-TEST-045` — a query and checking routine that reconciles every stored
answer's factual claims against its citation rows, reporting a percentage and naming any
answer with an uncited claim.
**Version under test:** `0.2.30`
**Time:** about 40 minutes, with a native inference process running.
**Who can run it:** anyone who can paste a line into a terminal and use a browser. Two steps
run a short Python one-liner inside the API container — it is pasted verbatim, nothing to
write.

**What is being checked.** `api/src/askwell/agent/citation_check.py`'s `check_citations` — it
re-segments each stored assistant message's text into claims independently (the same
`segment_claims` composition uses) and checks each claim's ordinal against the `citations`
table, rather than trusting that a citation row was ever written correctly. An answer with no
claims (an abstention) is compliant. An answer with a `fact_usage` row is excluded and counted
separately, not checked — nothing populates `fact_usage` before `M3`.

**What this ticket does not build.** There is no `scripts/dev.sh` subcommand for this and no
button anywhere — it is a query, not a screen (the ticket's own scope). It has to be invoked
either as a pytest suite (`api/tests/test_citation_check.py`, which is what actually runs in
CI) or, to reconcile *your own* real conversation data rather than a synthetic fixture, as a
short script run against the stack's network the same way `scripts/dev.sh db` and `test-db` do.
Both are shown below.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env`, find `POSTGRES_APP_PASSWORD`, and put any word after the `=` if it is blank.

### 1. Make a file to test with

```
mkdir -p ~/askwell-test/citecheck
cat > ~/askwell-test/citecheck/lease.md <<'EOF'
# Lease terms

The rent is due on the first of each month. Either party may terminate on
ninety days written notice. Late payments incur a five percent penalty.
EOF
```

### 2. Point Askwell at the folder and bring up the stack

In `.env`:

```
ASKWELL_ROOTS_MOUNT=/home/<you>/askwell-test/citecheck
```

```
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh web-build
```

### 3. Start native inference

```
scripts/dev.sh inference
```

Leave this running in its own terminal. **Expect:** the process reports a loaded model and
stays running. If no model is available in your environment, skip to **Part A** — it does not
need one — and read Known gaps for what Parts B–D cannot prove here.

---

## Part A — automated suite, read the output

```
scripts/dev.sh test-db
```

**Expect:** among the output, four tests from `api/tests/test_citation_check.py` pass — a
fully cited five-answer corpus reports 100%; deleting a citation row directly drops the
figure below the bar and names that exact answer with its quoted claim; an abstention counts
as compliant; a `fact_usage` row excludes rather than flags. This is the check itself,
verified against synthetic rows it inserts and cleans up — it does not touch anything you add
in the parts below.

---

## Part B — cold start, click through to a real cited answer

### 4. Open Askwell

`http://127.0.0.1:8000`. **Expect:** the Ask screen's first-run state — "Nothing added yet"
with an **Add a source** button.

### 5. Add the source

Click **Add a source**, point it at `~/askwell-test/citecheck`, and wait for `lease.md` to
reach **ready** in the ingest progress list (spinner stops).

### 6. Ask a question with a clean factual answer

Click into the composer, type **"When is rent due?"**, press **Enter**.

**Expect:** a step appears ("Searching your files.", then "Writing your answer."), then the
answer streams in and settles on something like "The rent is due on the first of each month."
with a citation marker rendered in the margin.

### 7. Ask a second question

Type **"What is the late payment penalty?"**, press **Enter**.

**Expect:** an answer citing the five percent penalty clause, same as step 6.

### 8. Ask a question the corpus cannot answer

Type **"What is the security deposit amount?"**, press **Enter**.

**Expect:** Askwell abstains — the answer says nothing in your files answers this, and names
what would need adding. No citation marker. This is the case the check must **not** flag.

---

## Part C — run the check against what you just asked

The check needs the stack's database network, the same one `scripts/dev.sh db` and `test-db`
join — `scripts/dev.sh run` is deliberately network-less (C1), so this pastes the equivalent
one-off invocation rather than inventing a new project command.

### 9. Run it

First read the three values `scripts/dev.sh db` itself uses, so the command below matches
what the stack was actually brought up with:

```
DB_USER="$(grep ^POSTGRES_USER .env | cut -d= -f2)"; DB_USER="${DB_USER:-askwell}"
DB_PASSWORD="$(grep ^POSTGRES_PASSWORD .env | cut -d= -f2)"
DB_NAME="$(grep ^POSTGRES_DB .env | cut -d= -f2)"; DB_NAME="${DB_NAME:-askwell}"
API_IMAGE="$(podman images --format '{{.Repository}}:{{.Tag}}' | grep -m1 askwell.*api)"
```

Then:

```
podman run --rm --network askwell_internal \
  -e ASKWELL_DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@postgres:5432/${DB_NAME}" \
  -v "$PWD":/app:z -w /app/api \
  "$API_IMAGE" \
  python -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.agent.citation_check import check_citations

async def main():
    engine = build_engine(Settings())
    async with session_factory(engine)() as session:
        result = await check_citations(session)
        print(f'checked={result.checked} compliant={result.compliant} excluded_fact_usage={result.excluded_fact_usage} pct={result.percentage}')
        for v in result.violations:
            print(f'VIOLATION message={v.message_id} claim={v.claim_text!r}')

asyncio.run(main())
"
```

**Expect:** `checked=2` (the two answered questions), `excluded_fact_usage=0`, `pct=100.0`, no
`VIOLATION` lines. The abstention from step 8 does not appear in `checked` at all unless it
also produced no claims and counted as compliant — either way it must not appear as a
violation.

If the container image name lookup above returns nothing, run `podman images` yourself and
substitute the API image's repository:tag directly.

### 10. Break it on purpose: delete a citation row

```
scripts/dev.sh psql -c "SELECT m.id, left(m.content, 60) FROM messages m WHERE m.role = 'assistant' ORDER BY m.created_at LIMIT 1;"
```

Note the `id` printed, then:

```
scripts/dev.sh psql -c "DELETE FROM citations WHERE message_id = '<id-from-above>' AND claim_ordinal = 1;"
```

### 11. Run the check again

Re-run the command from step 9.

**Expect:** `pct` drops below `100.0`, and one `VIOLATION` line names the exact `message_id`
you deleted the citation from, quoting the claim text from that answer — the sentence about
rent, verbatim.

---

## Part D — clean up

```
scripts/dev.sh psql -c "TRUNCATE conversations, messages, citations, fact_usage, audit_interactions CASCADE;"
```

---

## Known gaps

- **No project command runs this against real data.** `check_citations` exists as a Python
  function exercised by `test-db`; there is no `scripts/dev.sh` subcommand and no admin
  surface, so Part C pastes a one-off `podman run` rather than a documented command. This is
  the ticket's own stated scope — "a query, not a screen" — not a defect, but it means the
  walkthrough above is the closest thing to a repeatable manual check that exists today.
- **Memory-backed claims are excluded, not verified.** Any answer with a `fact_usage` row is
  skipped entirely rather than checked, because nothing populates that table before `M3`. A
  memory-backed answer with a genuinely uncited document claim would not be caught by this
  check today.
- **Segmentation disagreement can produce a false-positive violation.** The check re-segments
  claims with the same sentence-boundary regex composition uses; a sentence the model marked
  differently than the check would re-derive can surface as a violation that is actually a
  segmentation edge case, not a missing citation — which is why offending claims are quoted in
  full rather than only counted, so a human can tell the difference by reading it.
- **No reporting alongside eval runs yet.** The ticket calls for check results recorded
  alongside eval runs; `eval/bench.py` is `M1`-scoped but not built as of this version, so
  there is nowhere yet for this check's output to be attached automatically — it is read from
  the terminal, by hand, as done in Part C above.
