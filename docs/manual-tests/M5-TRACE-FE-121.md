# Manual test — M5-TRACE-FE-121, trace interactions: expand, click through, copy

**Ticket:** `M5-TRACE-FE-121` — the four interactions on the trace panel `M5-TRACE-FE-119`/
`M5-TRACE-FE-120` built (`web/components/ask/trace-panel.tsx`, `web/lib/trace.ts`): expanding a
step (already built, re-verified here), clicking a cited passage to open the source viewer at
that position and returning with the trace still open, clicking a memory fact to open the same
correct/delete popover an answer's claim uses (`web/components/ask/memory-chip.tsx`, split out of
`ask-screen.tsx` for this ticket), and a **Copy trace** button producing plain text
(`buildTraceCopyText` in `web/lib/trace.ts`).

**Version under test:** check `cat VERSION` (`0.4.38` at the time this document was written;
treat the working tree, not a tag, as what is under test if the two disagree).
**Time:** about 45 minutes, plus a first stack build and native inference running.
**Who can run it:** a browser, a terminal, `podman compose exec`/`scripts/dev.sh psql` access,
native `llama.cpp` inference running on the host (`scripts/dev.sh inference`).

**Where this stops on purpose — read before reporting anything below as a defect.**

- **A passage click-through only exists for a hit the answer actually cited.** `hitCitation` in
  `web/lib/trace.ts` matches a retrieved candidate to one of the answer's own citation cards by
  `chunkId`; a candidate that was retrieved but never cited (below threshold, or outscored for its
  claim) has no filename or passage text of its own to open, and its row still shows only the raw
  score, exactly as `M5-TRACE-FE-120` left it.
- **Threshold adjustment is not this ticket.** `docs/ux/trace.md` §4's "Adjust threshold — from an
  abstention trace only" is `M5-TRACE-FE-122`'s scope, listed as an Out of Scope item on this
  ticket itself.
- **A small local model's own choice of tool use, wording and citation cannot be forced.** Whether
  a turn cites a particular passage, draws on a memory fact, or produces the exact text below
  depends on the model actually behaving that way. Each scenario has a fallback (reading the code
  directly, or the unit suite) where a small local model might not cooperate.

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

### 4. Add the supplier agreement, by clicking

Click **Add a source**. In the **Files** section, click **Choose files** and select
`meridian-agreement.txt`. Answer any folder-nomination prompt by clicking its suggested folder.
**You should see:** the file appears in the batch list and moves to **Indexed** (or **Ready**)
within a few seconds.

---

## 1. Cold-start walkthrough — ask, open the trace, expand, click a passage, come back, click a fact, correct it, copy

### 5. Teach Askwell a memory fact

Go to **Ask**. In the composer, type:

```
For future reference, treat "the agreement" as shorthand for the Meridian Corp supplier
agreement whenever I ask about it.
```

Send it and let Askwell acknowledge or clarify as it does. Click **Memory** in the shell's own
navigation and confirm a fact now exists for this correction, marked as user-supplied. Click
**Ask** to go back.

### 6. Ask a question that uses both the document and that fact

```
Using the agreement, what is Meridian Corp's standard order minimum?
```

Click **Ask** (or press Enter) and wait for the answer to finish. **You should see:** an answer
naming `$2500`, with a citation card and a visible memory chip reading `"the agreement" =
Meridian Corp supplier agreement` (or similar) beside the claim it supported.

### 7. Open the trace

Click **How did you get this?** under the finished answer. **You should see:** the panel slide in
from the right, titled **How did you get this?**, with **Copy trace** and **Close** buttons in its
header and the numbered step sequence below.

### 8. Expand the retrieval step and read the full passage text

Find the `Searched your files` step and click **show detail**.

**You should see:** a `Threshold 0.65` line, then one row per retrieved passage. The passage that
matches the answer's own citation shows its score, the filename `meridian-agreement.txt`, and the
**full retrieved passage text underneath as a link** — not just the raw score `M5-TRACE-FE-120`
showed before this ticket.

### 9. Click the passage and confirm the viewer opens at that position

Click the passage text link.

**You should see:** the browser navigates to the source viewer (`/documents/?...`) showing
`meridian-agreement.txt`, scrolled or highlighted at the passage's position, with a right-hand rail
showing **From your question** (the question from step 6) and a **Back to answer** button.

### 10. Return and confirm the trace panel is still open

Click **Back to answer**.

**You should see:** you land back on the Ask screen at the same conversation, and — without
clicking **How did you get this?** again — the trace panel is already open, showing the same turn
you were reading before (`AskProvider`'s `openTraceTurnId` surviving the round trip through the
viewer, per the ticket's own Assumption). If it reopened collapsed, re-expand the `Searched your
files` step as in step 8.

### 11. Click the memory fact and confirm the answer's own popover opens

Find the `Checked your memory` step and click **show detail**. **You should see:** the fact from
step 5 rendered as the same clickable chip style used under the answer itself (small filled
confidence marker, `"the agreement" = Meridian Corp supplier agreement`).

Click the chip.

**You should see:** a popover opens in place — the identical **Memory fact** popover an answer's
own chip opens — showing the fact's subject and value, "You told me" with a date, usage count, and
**Correct** / **Delete** buttons.

### 12. Correct the fact from inside the trace panel

Click **Correct**, change the value (e.g. append " (net 30)"), and click **Save**.

**You should see:** a confirmation line naming reprocessing (e.g. a re-embedding label), and the
popover now showing the corrected value as current. Close the popover (click the `×` or click
elsewhere).

### 13. Copy the trace

Click **Copy trace** in the panel header.

**You should see:** the button label change to **Copied** for a couple of seconds, then revert to
**Copy trace**.

### 14. Paste the copied text somewhere and confirm it is readable

Paste into a plain text editor (or a fresh browser address bar to eyeball it, then discard).

**You should see:** plain text with no HTML or styling, starting with `Question: Using the
agreement, what is Meridian Corp's standard order minimum?`, a `Backend: local · <model>` line,
then a numbered line per step with its duration, a `Threshold 0.65` line and `Score N.NN` line(s)
under the retrieval step, and the `Wrote the answer` step's summary — everything needed to read the
trace without opening the app.

### 15. Close the panel and confirm you land back unchanged

Click **Close**. **You should see:** the panel disappears and the conversation is exactly as it
was, with keyboard focus back on the **How did you get this?** button.

---

## 2. A cited passage from a deleted document renders as deleted, not clickable

### 16. Delete the cited document

Go to the **Library**, find `meridian-agreement.txt`, and delete it (click its delete action and
confirm).

### 17. Reopen the trace for the earlier answer

Go back to **Ask**, scroll to the answer from step 6, and click **How did you get this?** again.
Expand the `Searched your files` step.

**You should see:** the passage row now reads the score, filename and page, plus `· deleted`, in
the same muted styling the answer's own citation cards use for a deleted source
(`provenance-margin.tsx`'s `useDeletion`). The passage text is shown as plain text, **not** a link
— clicking where the link used to be does nothing.

---

## 3. A fact deleted since the turn reads as unavailable, not correctable

### 18. Delete the memory fact from the Memory screen

Click **Memory** in the shell's navigation, find the corrected fact from step 12, and delete it
from there (not from the trace).

### 19. Reopen the same trace and try the chip

Back on **Ask**, open the trace for the answer from step 6 again and expand `Checked your memory`.

**You should see:** the fact row reads `This fact is no longer available.` in place of the
clickable chip — no popover offered, matching the ticket's own edge case that a fact deleted since
the turn should say so rather than offer to correct something gone.

---

## 4. Copying a very long trace states the truncation

This is impractical to force from a live turn with two small tools; confirmed directly against
the logic instead.

### 20. Run the unit test covering truncation

```
scripts/dev.sh web-run npx vitest run web/lib/trace.test.ts
```

**You should see:** the suite pass, including
`buildTraceCopyText truncates a very long trace and says so in the copied text`, which builds a
5000-hit retrieval step and asserts the copied text ends with `[Trace truncated for length.]` and
stays under the cap.

---

## 5. Run the rest of the unit suite directly

```
scripts/dev.sh web-run npx vitest run web/lib/trace.test.ts
```

**You should see:** the suite pass, including `hitCitation finds the citation card the answer
actually used for a hit`, `hitCitation is null for a candidate the answer never cited`, and the
`buildTraceCopyText` cases for question/backend/steps/scores/threshold, a rotated trace, and steps
left out by the ring buffer.

---

## 6. Clean up

```
podman compose down -v
rm -rf ~/askwell-test
```

**You should see:** no error.

---

## Known gaps

Not defects — deliberately not built by this ticket, or a later ticket's scope:

- **No threshold control.** `docs/ux/trace.md` §4's "Adjust threshold — from an abstention trace
  only" is `M5-TRACE-FE-122`'s scope, named as Out of Scope on this ticket itself. Nothing in the
  panel offers to change the retrieval threshold.
- **A passage click-through only exists for a retrieved hit the answer actually cited.** A
  near-miss or an outscored candidate — visible only as a raw score, same as `M5-TRACE-FE-120` —
  has no source to open, since the trace's own `{chunk_id, score}` pair carries no filename or
  passage text of its own outside a citation card.
- **Whether a real, small local model cites the exact passage or draws on the exact memory fact
  used in this walkthrough is not guaranteed on any given run** — same caveat every prior ticket in
  this epic records. If step 6 does not produce both a citation and a memory chip, re-ask more
  directly (e.g. `What does "the agreement" refer to, and what is its order minimum?`) before
  reporting a defect.
- **The local counter of trace copies (`getTraceCopiesCount` in `web/lib/trace.ts`) has no visible
  UI surface** — it is in-memory only, per the ticket's own Analytics Events line ("nothing
  transmitted"), and not displayed anywhere for this manual walkthrough to observe directly beyond
  reading the code or the unit suite.
