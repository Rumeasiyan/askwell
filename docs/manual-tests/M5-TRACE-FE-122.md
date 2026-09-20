# Manual test — M5-TRACE-FE-122, threshold adjustment from an abstention trace

**Ticket:** `M5-TRACE-FE-122` — the retrieval threshold control offered from an abstention
trace's near-miss (`web/components/ask/trace-panel.tsx`, `RetrievalThresholdControl`,
`docs/ux/trace.md` §4), and the same control with the same warning reachable from Settings
(`web/app/settings/page.tsx`, `docs/ux/settings.md` §2), both against one endpoint
(`GET`/`POST /settings/retrieval-threshold`, `askwell.retrieve.register_retrieval_threshold`)
that always writes an `audit_decisions` record.

**Version under test:** check `cat VERSION` (`0.4.39` at the time this document was written;
treat the working tree, not a tag, as what is under test if the two disagree).
**Time:** about 40 minutes, plus a first stack build and native inference running.
**Who can run it:** a browser, a terminal, `podman compose exec`/`scripts/dev.sh psql` access,
native `llama.cpp` inference running on the host (`scripts/dev.sh inference`).

**Where this stops on purpose — read before reporting anything below as a defect.**

- **A near-miss abstention is hard to force from a live small model with one short document.**
  This walkthrough forces one deterministically by raising the threshold from Settings *first*,
  above a score the model would normally clear, then asking a question that would otherwise
  answer. That is a legitimate way to reach `below_threshold` with a real hit above zero — it is
  not a workaround around the feature, it exercises the same code path a genuinely marginal
  question would.
- **No control on an empty-corpus or indexing abstention is the one edge case that does not need
  a near-miss forced** — it is reached by asking before any document exists at all.
- **A small local model's exact wording, and whether it answers a given question at all, cannot
  be forced.** Each scenario below names what to do if the model does not cooperate.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env` and confirm every `?set ... in .env` placeholder has a real value.

### Make a document corpus with one citable fact

```
mkdir -p ~/askwell-test/docs
cat > ~/askwell-test/docs/meridian-agreement.txt <<'EOF'
SUPPLIER AGREEMENT — MERIDIAN CORP — PAYMENT TERMS

Meridian Corp must be paid within 30 days of the invoice date. Contact for
disputes: meridian-ap@example.test. Standard order minimum: $2500.
EOF
```

**You should see:** one `.txt` file in `~/askwell-test/docs`.

---

## Cold start

### 1. Remove any previous state

```
podman compose down -v
```

**You should see:** containers and volumes reported removed, or a note there was nothing to
remove.

### 2. Bring the stack up, migrate, and start native inference

```
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** `postgres`, `sandbox`, `redis`, `egress-proxy`, `api`, `worker` all reported
created and started; migration finishing with no error.

In a separate terminal, on the host:

```
scripts/dev.sh inference
```

**You should see:** the inference process logging that it is listening on its socket. Leave it
running for the rest of this document.

### 3. Open Askwell as a first-time user

Open a browser at `http://127.0.0.1:8000`. **You should see:** the shell load with no alarm
banner, and the first-run empty state on the Ask screen.

---

## 1. No control on an empty-corpus abstention

### 4. Ask a question before any document exists

Go to **Ask**. Type:

```
What is Meridian Corp's standard order minimum?
```

Send it and wait. **You should see:** Askwell abstains — a plain statement that nothing in your
files answers this, naming that no documents have been added yet.

### 5. Open the trace and confirm no threshold control is offered

Click **How did you get this?** under the abstained answer. **You should see:** the panel opens,
shows an `abstain` step reading something like `empty_corpus`, and — critically — **no**
"closest passage scored..." line and **no** threshold input or **Change threshold** button
anywhere in the panel. Close the panel.

---

## 2. Raise the threshold from Settings, then force a near-miss abstention

### 6. Add the supplier agreement, by clicking

Click **Add a source**. In the **Files** section, click **Choose files** and select
`meridian-agreement.txt`. Answer any folder-nomination prompt by clicking its suggested folder.
**You should see:** the file appears in the batch list and moves to **Indexed** (or **Ready**)
within a few seconds.

### 7. Open Settings and find the retrieval threshold section

Click **Settings** in the shell's own navigation, then scroll to **Retrieval threshold**.

**You should see:** the warning copy in full — "Lowering the threshold makes Askwell answer
from weaker matches — more answers, more of them wrong. Raising it makes Askwell abstain more
often — fewer answers, but every one it gives is more likely to be right. There is no automatic
tuning: every change here is yours, and every change is recorded." — a `Current threshold: 0.65`
line, a number input pre-filled `0.65`, and a **Change threshold** button. No slider anywhere on
the page.

### 8. Raise the threshold to 0.95

Clear the number field, type `0.95`, and click **Change threshold**.

**You should see:** the button reads **Changing…** briefly, then a confirmation line: `Threshold
changed from 0.65 to 0.95. Recorded in the decisions log.` The **Current threshold:** line now
reads `0.95`.

### 9. Ask a question that would normally answer, and confirm it abstains instead

Go to **Ask** and send:

```
Using the supplier agreement, what is Meridian Corp's standard order minimum?
```

Wait for the turn to finish. **You should see:** Askwell abstains rather than answering with
`$2500` — the same document and question that would answer under the default `0.65` now falls
below the raised `0.95` threshold.

If the turn answers anyway: the model's own score for this passage happened to clear even
`0.95`. Raise the threshold further (e.g. `0.99`) from Settings and re-ask before treating this
as a defect.

### 10. Open the trace and read the near-miss line with the real scores

Click **How did you get this?**. Expand the `Searched your files` step.

**You should see:** a `Threshold 0.95` line, and the row for the supplier-agreement passage
showing its own score (something below `0.95`, e.g. `0.7x`) in the muted colour used for a score
that did not clear the bar.

Scroll to the bottom of the panel. **You should see:** below a rule, the same
`RetrievalThresholdControl` as Settings, now prefixed with a line reading `The closest passage
scored 0.7x, just under the 0.95 threshold.` using the **actual score from the step above**, not
a placeholder — check the two numbers match. The full warning paragraph, the `Current threshold:
0.95` line, the input and **Change threshold** button all appear exactly as in Settings.

---

## 3. Lower the threshold from inside the trace and confirm the same question now answers

### 11. Lower the threshold from the trace panel's own control

In the still-open panel, clear the input, type `0.5`, and click **Change threshold**.

**You should see:** `Changing…` then `Threshold changed from 0.95 to 0.5. Recorded in the
decisions log.` Close the panel.

### 12. Re-ask the identical question

Send the same question again:

```
Using the supplier agreement, what is Meridian Corp's standard order minimum?
```

**You should see:** Askwell now answers, naming `$2500`, with a citation card for
`meridian-agreement.txt` — the same passage that abstained a moment ago now clears the lowered
threshold.

### 13. Confirm the change is in the decisions log

```
scripts/dev.sh psql -c "SELECT payload ->> 'previous', payload ->> 'new', occurred_at FROM audit_decisions WHERE kind = 'retrieval_threshold_changed' ORDER BY occurred_at;"
```

**You should see:** three rows in order — `0.65 → 0.95` (step 8), `0.95 → 0.5` (step 11) — each
with its own timestamp, and no fourth row from anything else changing it.

---

## 4. An older trace still shows the threshold that was in force at the time

### 14. Reopen the trace from step 10 (the abstained turn under 0.95)

Scroll up to the abstained turn from step 9 and click **How did you get this?** again. Expand
`Searched your files`.

**You should see:** it still reads `Threshold 0.95` — unchanged by the two threshold changes made
since — because the stored trace captured the threshold in force at the moment that turn ran, not
a live read of today's setting.

---

## 5. Raising the threshold states the opposite consequence, and Settings and the trace never disagree

### 15. Raise the threshold again, from Settings this time

Go to **Settings**, set the threshold back to `0.95`, and click **Change threshold**.

**You should see:** the identical warning paragraph as steps 7 and 10 — it does not change
wording depending on whether you are raising or lowering; the single paragraph already states
both directions ("Lowering... Raising...").

### 16. Confirm the trace panel's control reads the same current value

Open the trace for any turn and scroll to its threshold control (only present if that turn's own
trace has a near-miss — reopen the abstained turn from step 9 if needed).

**You should see:** `Current threshold: 0.95`, matching what Settings now shows — the same
endpoint, read fresh, not a value cached from earlier in the session.

---

## 6. Clean up

```
podman compose down -v
rm -rf ~/askwell-test
```

**You should see:** no error.

---

## 7. Run the unit suite directly

```
scripts/dev.sh web-run npx vitest run web/lib/retrieval-threshold.test.ts
scripts/dev.sh test-db
scripts/dev.sh test eval/tests/test_abstain.py
```

**You should see:** the vitest suite pass, including `nearMiss` returning `null` for
`empty_corpus`/`source_indexing` and a populated result for `below_threshold`; `scripts/dev.sh
test-db` pass including `test_the_threshold_defaults_to_the_configured_value`,
`test_setting_the_threshold_is_read_back_and_used_by_retrieve`,
`test_changing_the_threshold_writes_a_decisions_record_with_old_and_new`, and
`test_setting_the_threshold_outside_zero_to_one_is_rejected` in `api/tests/test_retrieve_records.py`;
and the eval guard pass including
`test_retrieval_score_threshold_default_has_not_been_quietly_lowered` in
`eval/tests/test_abstain.py` — the ticket's own "guard test in the eval suite that catches a
default lowered without a decision."

---

## Known gaps

Not defects — deliberately not built by this ticket, or out of its scope entirely:

- **No automatic threshold tuning, ever** — the ticket's own Out of Scope line. Nothing in either
  surface suggests a value or adjusts one on the user's behalf; every change here is a person
  typing a number and clicking a button.
- **No guidance on what a good threshold is.** The control states the mechanical consequence of a
  change, never a recommendation — the ticket's own Known Gap, deliberate: the eval suite, not
  intuition, is meant to be the instrument for judging a chosen value.
- **The local counter of threshold changes** (`getThresholdChangesCount` in
  `web/lib/retrieval-threshold.ts`) has no visible UI surface — in-memory only, per the ticket's
  own Analytics Events line ("nothing transmitted", C1) — not observable in this walkthrough
  beyond reading the code or the unit suite.
- **Whether a real, small local model answers or abstains at a given threshold is not exactly
  reproducible run to run.** The scores named in this document (`0.7x`) are illustrative; check
  the trace panel's own numbers against each other (the near-miss line vs. the retrieval step
  detail), not against the literal figures printed here.
