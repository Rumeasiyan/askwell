# Manual test — M5-LOOP-BE-116, the eight-call ceiling, gathered work and Continue

**Ticket:** `M5-LOOP-BE-116` — `askwell.agent.loop.run_tool_loop` now enforces a hard ceiling of
8 tool calls per turn. Reaching it stops the turn, composes an answer from whatever was actually
gathered (never presented as complete), states plainly that it stopped early, and — on a turn's
first stop — offers a **Continue** that starts a fresh turn carrying the gathered history forward
rather than repeating it. A second stop in the same chain narrows the text instead of offering a
third continuation.
**Version under test:** check `cat VERSION`.
**Time:** about 60 minutes, plus a first stack build and native inference running.
**Who can run it:** a browser, a terminal, `podman compose exec`/`scripts/dev.sh psql` access,
native `llama.cpp` inference running on the host (`scripts/dev.sh inference`) — like
`M5-LOOP-BE-115`, this is about what the model itself decides to call, so nothing here works
against a stack with no model loaded.

**What is being checked.** `api/src/askwell/agent/loop.py` (`CALL_CEILING`, `_stop_at_ceiling`,
`LoopContinuation`, `LoopResult.pending_calls`/`.continuation`/`.continuation_count`), and its
wiring into `api/src/askwell/ask.py` (`AskRequest.continue_from`, `_load_loop_continuation`, the
`tool_ceiling`/`can_continue` fields on the `done` event, and `ASK_ASKED`'s own `tool_ceiling`
audit field). Backed by `api/tests/test_loop.py`'s five ceiling tests (a truncated batch, a
one-at-a-time approach to the same ceiling, nothing gathered, a `Continue` resume, and a second
stop narrowing instead of continuing). This document repeats the ceiling's headline behaviour —
a stopped-early answer that is honest about it, and a `Continue` that makes progress rather than
repeating — against a cold-started stack with a real model, which the automated suite fakes.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **There is no "Tool ceiling hit" state or Continue button in `web/`.** `docs/ux/ask.md` §5's
  row for it and `docs/states-and-edge-cases.md` §2's matching row have nothing built against
  them yet (`grep -rn "can_continue|continue_from|tool_ceiling" web/app web/components` finds
  nothing) — this ticket's own label is `phase:4, backend`, and the FE half is separate,
  unstarted work. §2 below reads what a stopped turn actually produced from `messages`/the SSE
  stream with `psql`/`curl`, and §3 exercises `continue_from` the same way a click would send it,
  since there is no click to make yet.
- **There is still no trace panel.** Same gap `M5-LOOP-BE-115.md` already recorded for
  `docs/ux/trace.md` — `pending_calls` ("what it was about to do") is read back from
  `messages.trace` directly, not from a panel.
- **A small local model does not reliably use its full context in exactly 8 calls on command.**
  The corpus below is built to make many distinct lookups attractive, and the fallback guidance
  in §1 exists because a real model may compose an answer in 3 calls just as easily as 9. Where
  a step's outcome depends on the model actually reaching the ceiling, that is called out.
- **The "ceiling reached with nothing useful gathered" edge case is not driven end-to-end
  through the browser.** Forcing every one of 8 real tool calls to fail on purpose, on a corpus
  that also has to look hybrid enough to enter the loop at all, is not something a typed question
  can reliably cause. `api/tests/test_loop.py`'s
  `test_the_ceiling_reached_with_nothing_gathered_never_composes_from_nothing` is the authoritative
  proof for it; §4 below reproduces the same shape with a script against the real loop instead.

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

### Make a document corpus with several distinct, separately-searchable facts

Five short files, each naming one supplier with its own distinct terms — separate documents so a
broad question has a real reason to search more than once or twice.

```
mkdir -p ~/askwell-test/docs
for n in Acme Globex Initech Umbrella Wayne; do
cat > ~/askwell-test/docs/${n,,}-agreement.txt <<EOF
SUPPLIER AGREEMENT — ${n} CORP — PAYMENT TERMS

${n} Corp must be paid within $((RANDOM % 20 + 20)) days of the invoice date. Contact for
disputes: ${n,,}-ap@example.test. Standard order minimum: \$$((RANDOM % 4000 + 1000)).
EOF
done
```

**You should see:** five `.txt` files in `~/askwell-test/docs`, each with a different payment
term, contact address and order minimum — five separate facts, not one repeated fact.

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

### 4. Add all five supplier agreements, by clicking

Click **Add a source**. In the **Files** section, click **Choose files** and select all five
files in `~/askwell-test/docs`. Answer any folder-nomination prompt by clicking its suggested
folder. **You should see:** all five files appear in the batch list, each moving to **Indexed**
(or **Ready**) within a few seconds.

### 5. Stand up a database to connect to

Plays the part of a database the user already runs — inside `sandbox`, the same pattern
`M5-LOOP-BE-115.md` and `M4-CONN-FE-096.md` use.

```
podman compose exec sandbox psql -U "$(grep ^SANDBOX_POSTGRES_USER .env | cut -d= -f2)" -d postgres <<'SQL'
CREATE DATABASE ceiling_test OWNER askwell_sandbox_owner;
SQL
```

**You should see:** `CREATE DATABASE`.

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d ceiling_test <<'SQL'
CREATE TABLE payments (
    supplier text not null,
    invoice_date date not null,
    paid_date date not null
);
INSERT INTO payments VALUES
    ('Acme Corp', '2026-06-01', '2026-07-16'),
    ('Globex Corp', '2026-06-01', '2026-06-20'),
    ('Initech Corp', '2026-06-01', '2026-07-28'),
    ('Umbrella Corp', '2026-06-01', '2026-06-25'),
    ('Wayne Corp', '2026-06-01', '2026-08-02');
GRANT CONNECT ON DATABASE ceiling_test TO askwell_sandbox_readonly;
GRANT USAGE ON SCHEMA public TO askwell_sandbox_readonly;
GRANT SELECT ON payments TO askwell_sandbox_readonly;
SQL
```

**You should see:** `CREATE TABLE`, `INSERT 0 5`, three `GRANT`s.

Note the readonly password:

```
grep ^SANDBOX_READONLY_PASSWORD .env
```

### 6. Connect to it, by clicking

Still on **Add a source**, in the **Connect a database** section: Engine `PostgreSQL`, Host
`sandbox`, Port `5432`, Database `ceiling_test`, User `askwell_sandbox_readonly`, Password (the
value from step 5). Click **Connect**.

**You should see:** a queued/ready confirmation naming `ceiling_test`; the library shows it as
**Ready** after a few seconds.

---

## 1. A broad question stops at 8 calls, with what was gathered and a plain note it stopped early

### 7. Ask a deliberately broad question

Go to **Ask**. In the composer, type:

```
For every supplier we have on file — Acme, Globex, Initech, Umbrella and Wayne — tell me their
payment term from the contract, their dispute contact, their order minimum, and how many days
late (if any) they were actually paid according to the database.
```

Click **Ask** (or press Enter). This names five suppliers across two kinds of source, four facts
each — twenty distinct lookups on offer, deliberately more than the model could reasonably answer
from memory or a single call.

**You should see, while it is working:** named steps join with " · " as they land — at minimum
`Checking your connected databases.` and `Working through this in steps.`, then a run of
`Called document_search.` / `Called database_query.` labels as the model works through suppliers.

**You should see, once it finishes, if the ceiling was reached:** the last step label reads
`Stopped after 8 steps for this question.`, and the answer prose ends with a sentence to the
effect of *"Askwell stopped after reaching its 8-step limit for this question — this is what it
found before then, not a complete answer."* — the exact wording of `_CEILING_NOTE` in
`api/src/askwell/agent/loop.py`. The answer body above that note should name at least one real
fact it actually gathered (a term, a contact, a days-late figure) rather than being empty prose.

**If the model answered in fewer than 8 calls instead:** that is a legitimate outcome, not a
bug — nothing forces the ceiling, only invites it. Ask a pointed follow-up in the same
conversation naming every one of the twenty facts explicitly and asking for each individually,
e.g. "List, one line per supplier: Acme's term, Acme's contact, Acme's minimum, Acme's days late,
then the same four for Globex, then Initech, then Umbrella, then Wayne." A small local model is
far more likely to emit one tool call per named item when the items are spelled out this
explicitly. If it still does not reach 8, proceed to §4, which forces the ceiling directly against
the real loop rather than depending on what the model chooses.

### 8. Confirm the note is never missing

Re-read the final sentence of the answer from step 7. **You should see:** the stopped-early note
present verbatim, not paraphrased or dropped — this ticket's own Validation Rule
("A stopped-early answer must never omit the note").

---

## 2. The trace shows what it was about to do, and the turn is marked as a ceiling stop

### 9. Find the message id

```
scripts/dev.sh psql -c "SELECT id, content FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
```

Note the `id` — call it `$MSG_ID`.

### 10. Confirm the top-level trace records the ceiling stop

```
scripts/dev.sh psql -c "
SELECT trace->>'loop_stopped_reason',
       trace->>'stopped_early',
       trace->>'loop_continuation_count',
       jsonb_array_length(COALESCE(trace->'loop_pending_calls', '[]'::jsonb)) AS pending_count
FROM messages WHERE id = '$MSG_ID';
"
```

**You should see (only if step 7 actually hit the ceiling):** `loop_stopped_reason` reading
`tool_ceiling`, `stopped_early` reading `true`, `loop_continuation_count` reading `1`. Silently
truncating and presenting the result as complete is exactly what `stopped_early = true` on the
record is there to rule out.

### 11. Read back what it was about to do

```
scripts/dev.sh psql -c "SELECT trace->'loop_pending_calls' FROM messages WHERE id = '$MSG_ID';"
```

**You should see:** either an empty array (the ceiling was discovered only at the *next*
iteration — `_stop_at_ceiling`'s own forced compose call, which may itself ask for one more tool)
or a JSON array of `{"tool": ..., "arguments": ...}` objects — a batch that would have crossed 8
was truncated there, and these are the calls that never ran. Either shape is correct; both are
covered by `api/tests/test_loop.py`'s two "reaches the ceiling" tests. What matters is that this
column exists and is not silently empty when the model's last batch was larger than the
remaining budget — try step 7 again with an even more itemised question if you saw a truncated
batch you'd like to inspect here.

### 12. Confirm the ceiling stop reached the audit log, not only the trace ring buffer

```
scripts/dev.sh psql -c "
SELECT payload->>'tool_ceiling', payload->>'message_id'
FROM audit_interactions
WHERE payload->>'message_id' = '$MSG_ID';
"
```

**You should see:** one row, `tool_ceiling` reading `true` — this ticket's own Audit / Logging
Requirement, and the reason the count survives even after `docs/audit-log.md`'s trace ring buffer
rotates old detail away.

---

## 3. Continue starts a new turn that makes progress, not a repeat

There is no **Continue** button in `web/` yet (see "Where this stops on purpose"). This section
sends exactly what a click would send — `continue_from` set to the stopped turn's own id — so the
backend behaviour is exercised the same way a future click will exercise it.

### 13. Confirm the turn is continuable

```
scripts/dev.sh psql -c "SELECT trace->>'loop_continuation' IS NOT NULL AS has_continuation FROM messages WHERE id = '$MSG_ID';"
```

**You should see:** `t`. This is `LoopContinuation.as_dict()`, persisted at the first stop —
`can_continue` on the live `done` event is derived from the same value.

### 14. Send the same question again, naming `continue_from`

```
curl -s -X POST http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -d "{\"question\": \"For every supplier we have on file — Acme, Globex, Initech, Umbrella and Wayne — tell me their payment term from the contract, their dispute contact, their order minimum, and how many days late (if any) they were actually paid according to the database.\", \"continue_from\": \"$MSG_ID\"}" \
  | head -c 400
```

**You should see:** the beginning of an SSE stream (`event: step` / `event: token` lines) — the
request was accepted, not rejected as a malformed body.

### 15. Confirm the new turn actually made progress

```
scripts/dev.sh psql -c "SELECT id, content FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
```

Note the new `id` as `$MSG_ID2` (it must differ from `$MSG_ID`).

```
scripts/dev.sh psql -c "
SELECT step->>'tool', step->>'arguments'
FROM messages, jsonb_array_elements(trace->'steps') AS step
WHERE id = '$MSG_ID2' AND step->>'kind' = 'tool'
ORDER BY (step->>'result_index')::int;
"
```

**You should see:** tool calls for suppliers or facts that were **not** already answered in the
first turn's prose — the continuation's whole point is a fresh budget spent on what is still
missing, not the same eight calls run again. Compare against the first turn's answer text
(`SELECT content FROM messages WHERE id = '$MSG_ID';`) to confirm nothing here is a repeat.

### 16. Confirm the new turn's own budget is a fresh 8, not inherited

```
scripts/dev.sh psql -c "SELECT trace->>'loop_stopped_reason' FROM messages WHERE id = '$MSG_ID2';"
```

**You should see:** either `answered` (the continuation finished the question within its own 8
calls) or `tool_ceiling` again (a third round of facts still to gather) — both are legitimate;
what would be wrong is the turn stopping at 0 calls because it thought its budget was already
spent from the first turn.

### 17. A second stop in the same chain narrows instead of offering a third Continue

Only run this if step 16 showed `tool_ceiling` again.

```
scripts/dev.sh psql -c "SELECT content, trace->>'loop_continuation' IS NOT NULL AS has_continuation FROM messages WHERE id = '$MSG_ID2';"
```

**You should see:** `has_continuation` reading `f`, and `content` ending with a sentence to the
effect of *"This question has now stopped twice without finishing — it may need narrowing."*
(`_NARROW_AGAIN_NOTE`) — told plainly rather than being offered a third continuation
(`continuation_count >= 1` in `_stop_at_ceiling`).

---

## 4. The ceiling reached with nothing gathered composes nothing, honestly

Reproduces `api/tests/test_loop.py`'s
`test_the_ceiling_reached_with_nothing_gathered_never_composes_from_nothing` against the real
loop with a scripted fake model, rather than depending on a real model's tool choices to fail
every one of 8 real calls on purpose (see "Where this stops on purpose").

### 18. Run the scripted repro inside the API container

```
scripts/dev.sh run python - <<'PY'
import asyncio, json
from unittest.mock import AsyncMock, patch
from askwell.agent import loop as loop_module
from askwell.agent.tools import ToolError, ToolErrorCode, ToolResult, ToolStep


class _FakeClient:
    def __init__(self, text: str) -> None:
        self._text = text

    async def generate(self, prompt: str, **_: object):
        class _Completion:
            text = self._text

        return _Completion()


async def _fake_call_tool(name, arguments, **_):
    result = ToolResult(content=None, truncated=False,
                         error=ToolError(ToolErrorCode.NOT_FOUND, "no match"))
    step = ToolStep(kind="tool", tool=name, arguments=arguments, duration_ms=1,
                     outcome="not_found", truncated=False, detail={},
                     injection_flagged=False, injection_patterns=())
    return result, step


async def main() -> None:
    calls = json.dumps({
        "type": "tool_calls",
        "calls": [{"tool": "document_search", "arguments": {"query": f"q{i}"}} for i in range(1, 9)],
    })
    client = _FakeClient(calls)
    with patch("askwell.agent.loop.call_tool", _fake_call_tool):
        result = await loop_module.run_tool_loop(
            None, None, client, question="Everything about a supplier that does not exist?"
        )
    print("stopped_reason:", result.stopped_reason)
    print("text:", result.text)
    assert result.stopped_reason == "tool_ceiling"
    assert result.text == loop_module._NOTHING_GATHERED_TEXT
    print("OK: nothing-gathered edge case composes honestly, not from nothing")


asyncio.run(main())
PY
```

**You should see:** `stopped_reason: tool_ceiling`, `text:` printing the `_NOTHING_GATHERED_TEXT`
copy ("Askwell reached its 8-step limit for this question without finding anything useful to
answer from. Try narrowing the question, or check that the right sources are connected."), and the
final `OK:` line — the ceiling reached with nothing gathered never invents an answer, matching
this ticket's own named edge case.

---

## 5. Clean up

```
podman compose down -v
rm -rf ~/askwell-test
```

**You should see:** no error.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not demonstrable in this environment:

- **No "Tool ceiling hit" UI and no Continue button.** `docs/ux/ask.md` §5 and
  `docs/states-and-edge-cases.md` §2 both describe it; nothing in `web/` renders it yet. §1 reads
  the answer text and step labels that already stream to the browser; §3 sends `continue_from`
  with `curl` in place of a click.
- **No trace panel.** Same standing gap as `M5-LOOP-BE-115.md` — `pending_calls` is read from
  `messages.trace` with `psql`, not a panel.
- **The ceiling is not adjustable in v1**, by this ticket's own Out of Scope — nothing above
  attempts to raise it.
- **"Nothing gathered" is exercised with a scripted fake model (§4), not a real one.** Forcing a
  real small model to make 8 real tool calls that all genuinely fail, on a corpus that still
  looks hybrid enough to enter the loop, is not reliably drivable through the browser.
- **Whether a real model reaches the ceiling at all is not guaranteed by this document** — §1's
  fallback guidance exists because the exact number of calls a small local model chooses to make
  is its own decision, not something a question can force byte-for-byte, same caveat
  `M5-LOOP-BE-115.md` already recorded for tool choice generally.
