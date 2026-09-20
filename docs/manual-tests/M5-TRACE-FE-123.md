# Manual test — M5-TRACE-FE-123, trace states including the rotated-away trace

**Ticket:** `M5-TRACE-FE-123` — the seven trace states from `docs/ux/trace.md` §5: normal,
abstention, partial, tool ceiling, failed mid-answer, online backend, trace unavailable. The
unavailable state must say plainly that the detailed trace was cleared and that the answer and
its sources survive, and the answer's own citations must still open after rotation.
**Version under test:** `0.5.0`
**Time:** about 45 minutes, with a native inference process running.

**What is being checked.** `web/lib/trace.ts` (`isFailedTrace`, `isPartialTrace`,
`isOnlineBackend`, `toolCeilingPendingCalls`, and the `trace_rotated` field read straight from the
API) and `web/components/ask/trace-panel.tsx`'s `TraceBody`, which picks between the unavailable
message, the ordinary step sequence, `FailedNote`, `PartialNote`, `ToolCeilingNote`, and
`BackendLine`. Server side, `api/src/askwell/traces.py`'s `TraceRing.prune()` and
`api/src/askwell/ask.py`'s `_trim_rotated_traces` are what actually rotate a trace out and set
`trace_rotated: true` on `messages.trace`, leaving `citations` untouched.

**Where this stops on purpose.** The online-backend state (`docs/ux/trace.md` §5's "Marked, with
what was sent") is unreachable before M8 — nothing in this build ever writes `backend.mode:
"online"` — so Part F below is a code read, not a browser click. Reaching the tool-call ceiling
(Part D) depends on the model's own behaviour for a given question, not on anything this
walkthrough can force deterministically.

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

---

## Cold start

### 1. Build the interface

```
scripts/dev.sh web-build
```

**You should see:** a Next.js build finishing with a route list and no red error text.

### 2. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait
about thirty seconds.

### 3. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 4. Start native inference

```
scripts/dev.sh inference
```

Leave this running in its own terminal. **You should see:** the process report a loaded model and
stay running.

### 5. Open Askwell

Open a browser at:

```
http://127.0.0.1:8000
```

**You should see:** the **Ask your own material** first-run page.

### 6. Add a source with two distinct, checkable facts

Click **Add a source**. Add one file that covers two separate, narrow topics you can ask about
independently (e.g. a document with both a return-policy section and a shipping-times section).
Wait for it to reach `ready` — its row in the ingest progress list stops showing a spinner.

### 7. Return to Ask

Click **Ask** in the left strip (or the Askwell wordmark).

---

## Part A — the normal state

### 8. Ask a question the source actually answers

Type a question about one of the two topics from step 6, press **Enter**.

**You should see:** named retrieval steps, then streaming answer text, then a populated margin
with at least one source card.

### 9. Open the trace

Click **How did you get this?** under the answer.

**You should see:** a panel sliding in from the right, titled "How did you get this?", with a
**Copy trace** and **Close** button at the top, and below that a numbered sequence of steps —
each with a plain-language summary and, where the step carries one, a duration on the right. A
`Local · <model name>` line sits above the sequence.

### 10. Confirm nothing else is showing

**You should not see:** any "cleared" message, any red/alarm-coloured text, any "Not covered by
your files" note, or any "Stopped after 8 steps" note. This is the plain baseline the other states
contrast against.

### 11. Close the panel

Click **Close**.

**You should see:** the panel closes and keyboard focus returns to the **How did you get this?**
button you opened it from (confirm by pressing **Tab** once and checking focus moved to the next
element after that button, not from the top of the page).

---

## Part B — the abstention state

### 12. Ask a question the source does not cover

Type a question clearly unrelated to anything in the source you added (e.g. "What was our Q3
revenue in the Nairobi office?"). Press **Enter**.

**You should see:** the abstention text block, not a streamed answer.

### 13. Open its trace

Click **How did you get this?**.

**You should see:** a **retrieve** step reading something like "Searched your files — nothing came
back" or naming a low top score, with a **Threshold `0.xx`** line above the list of scores when you
expand "show detail". No "Not covered by your files" note, no failed note, no tool-ceiling note —
this trace is otherwise exactly as informative as Part A's, just showing a search that came back
empty or too weak.

### 14. Check for the near-miss control

If the closest score is below the threshold but not by much, **you should see** a control near the
bottom of the panel stating the closest score and the threshold, and warning that lowering the
threshold means more answers, more of them wrong — not a bare slider. If nothing scored close, you
should see no such control, which is correct.

### 15. Close the panel

---

## Part C — the partial state

### 16. Ask a question that spans both topics from step 6, where the source only fully covers one

Ask something like "What's the return window, and what's our policy on same-day shipping refunds?"
— phrased so one half is answerable from the source and the other is not.

**You should see:** an answer that addresses the covered half, followed by a visually distinct
block (left border, "Not covered by your files" label) naming what it could not answer.

If the model answers both halves fully, rephrase to make the uncovered half more clearly outside
the source's content and re-ask — partial coverage depends on the model actually leaving something
out, not on the question's wording alone.

### 17. Open its trace

**You should see:** the same left-border "Not covered by your files" block reproduced inside the
trace panel, near the bottom, listing the same uncovered aspect(s) as the answer body — not a
different or reworded list.

### 18. Close the panel

---

## Part D — the tool-ceiling state (best effort)

### 19. Connect a live database or dump, if you have not already

If no database source is connected yet, add one (`Add a source` → connect a database or import a
dump) so multi-step tool use is possible at all — a document-only corpus rarely drives enough tool
calls to reach the ceiling.

### 20. Ask a question that plausibly needs many small steps

Ask something that spans several unrelated lookups in one question, e.g. "List every table you can
query, then tell me the row count of each one, then tell me today's date." Press **Enter**.

**You should see either:** an ordinary answer (the model finished in fewer than 8 tool calls — this
is the common outcome and is not a defect), **or**, if the ceiling was hit, a note under the answer
that it stopped partway.

### 21. If the ceiling was hit, open its trace

**You should see:** the steps actually taken, followed by a note reading "Stopped after 8 steps for
this question." and, if the model had another call queued, a line naming what it was about to call.

**If the ceiling was not hit after a couple of tries,** record that as the outcome rather than
forcing it further — this state's Testing Notes describe it as best-effort, and the ceiling exists
to bound a rare case, not one this walkthrough can script.

### 22. Close the panel

---

## Part E — the failed-mid-answer state

### 23. Stop native inference mid-question

Ask a new question. While the retrieval/generation steps are visibly still in progress, switch to
the terminal running `scripts/dev.sh inference` and stop it (**Ctrl+C**).

**You should see:** the turn ends in a failure state on screen (an "assistant unavailable" or
similar message, in `--alarm`/red-toned text).

### 24. Open its trace

**You should see:** whatever steps had already run before the failure (possibly none, if it failed
before retrieval started), followed by a note in `--alarm`-coloured text naming the failure reason
— not a blank panel and not the ordinary "Wrote the answer" final step, since generation never
reached that point.

### 25. Restart inference

```
scripts/dev.sh inference
```

Leave it running in its own terminal again before continuing to the next part.

---

## Part F — the online-backend state (code check, not a browser step)

This state is unreachable in this build — read `web/components/ask/trace-panel.tsx`'s
`BackendLine` and `web/lib/trace.ts`'s `isOnlineBackend` instead of trying to trigger it:

### 26. Confirm the field exists and is wired, without a way to reach it

**You should see, reading the code:** `BackendLine` renders `trace.backend.mode` and
`trace.backend.model` whenever `trace.backend` is present at all, and adds a "show what was sent"
disclosure specifically when `isOnlineBackend(trace)` is true and `trace.backend.sent` is set.
Nothing in `api/src/askwell/ask.py` ever writes `backend.mode` as anything but `"local"` in this
build — confirm with:

```
grep -rn '"mode"' api/src/askwell/ask.py
```

**You should see:** every match sets `"mode": "local"`. This state existing-but-unreachable is the
correct, intended state for M5 — not a defect to report.

---

## Part G — the rotated/unavailable trace, and its citation still opening

This forces the ring buffer to rotate by shrinking its cap, then confirms the old answer's own
citation still works even though its trace is gone.

### 27. Note today's answered turn to re-check later

Pick the turn from Part A (the normal answer). Note its question text so you can find it again
after other turns push it down the conversation.

### 28. Shrink the trace cap

Stop the stack:

```
podman compose down
```

Open `.env`, find (or add, if the line is not already present) `ASKWELL_TRACE_MAX_BYTES`, and set
it to a very small value:

```
ASKWELL_TRACE_MAX_BYTES=4096
```

### 29. Bring the stack back up

```
podman compose up -d
scripts/dev.sh db upgrade head
```

Restart native inference in its own terminal if it is not still running:

```
scripts/dev.sh inference
```

**You should see:** the same conversation history from before still listed on the Ask screen — the
cap change does not touch `messages` or `citations`, only the trace ring buffer's own directory.

### 30. Ask a few more questions to force rotation

Ask three or four more distinct questions (any topic, covered or not), waiting for each to finish
before asking the next.

**You should see:** each answers normally. Nothing on screen indicates rotation yet — it happens
silently in the background each time a new trace is written and the ring buffer prunes to fit.

### 31. Open the trace on the turn noted in step 27

Scroll back to that turn and click **How did you get this?**.

**You should see:** none of the step sequence from Part A. Instead, exactly this text: "The
detailed trace for this answer has been cleared. The answer and its sources are still in your
log." — no error styling, no red/alarm colour, and no **Copy trace** button showing step content
(re-check: **Copy trace** is still present and, if clicked, produces text stating the trace was
cleared rather than an empty or broken paste).

### 32. Close the panel and check the answer's own citation

With the trace panel closed, look at the same turn's answer text and its margin/citation card.

**You should see:** the citation card is still there, still naming its source file and page,
exactly as it did before you shrank the cap — rotation touched only the trace, never `citations`.

### 33. Click the citation

**You should see:** it opens the source viewer at the right document and position, exactly as it
would for any other answer's citation. This is the concrete proof of the Acceptance Criteria's
"the answer's citations still open."

### 34. Restore the trace cap

Stop the stack, remove or restore the `ASKWELL_TRACE_MAX_BYTES` line in `.env` to match
`.env.example` (`268435456`), and bring the stack back up:

```
podman compose down
```

Edit `.env` to restore the line, then:

```
podman compose up -d
scripts/dev.sh db upgrade head
```

---

## Known gaps

- **The online-backend state (Part F) cannot be reached from the browser in this build.** M8 has
  not landed; nothing writes `backend.mode: "online"` yet. The check above confirms the rendering
  code is ready, not that it works end to end — that is M8's own manual test to write.
- **The tool-ceiling state (Part D) cannot be forced deterministically.** Whether a question drives
  8 tool calls depends on the model's own step-by-step decisions, not on anything the question's
  wording guarantees. Recording "not reached after N tries" is an acceptable outcome for this
  walkthrough, not a defect.
- **A partially-rotated trace (some steps dropped, not all) is not exercised here.** The code path
  that treats a partial rotation as fully unavailable rather than rendering an incomplete sequence
  is asserted by an automated test, not reachable by shrinking `ASKWELL_TRACE_MAX_BYTES` from the
  browser alone — the ring buffer drops whole trace files, not partial ones, so this walkthrough's
  Part G only ever produces the fully-rotated case.
- **Trace retention's real-world default is still open**, tied to the log-budget work in M7
  (`docs/ux/trace.md` §6.2: 20% of the log budget, roughly 400 MB at the 2 GB default). Part G's
  `ASKWELL_TRACE_MAX_BYTES=4096` is a test-only value to force rotation quickly, not a preview of
  the shipped default.
- **Depends on a real model and real retrieval**, same as every trace-family ticket since
  `M5-TRACE-FE-119`: without `scripts/dev.sh inference` running, nothing past step 7 can be
  exercised.
