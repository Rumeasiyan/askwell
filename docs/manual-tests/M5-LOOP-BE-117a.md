# Manual test — M5-LOOP-BE-117a, live per-call tool step events

**Ticket:** `M5-LOOP-BE-117a` — `run_tool_loop` (`api/src/askwell/agent/loop.py`) now takes an
optional `on_tool_call` observer that fires a `"start"` event immediately before a tool call is
dispatched and an `"end"` event immediately after it returns, once per call actually run
(never for a deduplicated one). A parallel batch's `"start"` events all fire before any of that
batch's `"end"` events. `api/src/askwell/ask.py`'s two loop call sites wire this in and emit a
live `step` event from the `"end"` phase, replacing the old shape where every tool-call label
appeared in one burst only after the whole loop had finished.

**Version under test:** check `cat VERSION` (`0.4.33` at the time this document was written).
**Time:** about 40 minutes, plus a first stack build and native inference running.
**Who can run it:** a browser with developer tools, a terminal, `podman compose exec`/
`scripts/dev.sh psql` access, native `llama.cpp` inference running on the host
(`scripts/dev.sh inference`) for §1–§2 — like the rest of this epic, a real model's own choice
of which tools to call cannot be forced turn by turn. §3 reproduces the observer's own contract
directly against the real loop code with a stubbed model and stubbed tools, and needs no model
running at all.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **`"start"` events are not rendered.** `api/src/askwell/ask.py`'s `_emit_tool_call_step`
  deliberately returns early on `event.phase != "end"` — the frontend has no start/end
  discriminator to collapse a pair into one label yet (`M5-LOOP-FE-118`, issue #420), so
  emitting both today would double every visible label. What §1 below actually watches for is
  the *timing* of the `"Called {tool}."` labels that do ship — one per call, live, as that call
  itself finishes — not a start label appearing first.
- **No trace panel.** Every step is read back with `psql` against `messages.trace`, or watched
  live in the browser's own developer tools against the SSE stream — `docs/ux/trace.md`'s
  rendered panel is a later ticket.
- **A small local model does not reliably call two tools in the same turn on command.** §1 uses
  a corpus and a question built to make a hybrid (file + database) turn likely, the same
  approach `M5-LOOP-BE-115.md`/`-116.md`/`-117.md` already used, with a documented fallback if
  the model chooses otherwise.
- **Citations for a loop-answered turn are a separate, later concern** (issue #407) — not
  checked here.

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

### Make a document corpus with one distinct, quotable fact

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
banner, and the first-run empty state on the Ask screen. Open the browser's developer tools
now (e.g. F12) and switch to its Network tab — you will use it in §1.

### 4. Add the supplier agreement, by clicking

Click **Add a source**. In the **Files** section, click **Choose files** and select
`meridian-agreement.txt`. Answer any folder-nomination prompt by clicking its suggested folder.
**You should see:** the file appears in the batch list and moves to **Indexed** (or **Ready**)
within a few seconds.

### 5. Stand up a database to connect to

Plays the part of a database the user already runs, same pattern as `M5-LOOP-BE-115.md`,
`-116.md` and `-117.md`.

```
podman compose exec sandbox psql -U "$(grep ^SANDBOX_POSTGRES_USER .env | cut -d= -f2)" -d postgres <<'SQL'
CREATE DATABASE stepevents_test OWNER askwell_sandbox_owner;
SQL
```

**You should see:** `CREATE DATABASE`.

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d stepevents_test <<'SQL'
CREATE TABLE payments (
    supplier text not null,
    invoice_date date not null,
    paid_date date not null
);
INSERT INTO payments VALUES
    ('Meridian Corp', '2026-06-01', '2026-07-16');
GRANT CONNECT ON DATABASE stepevents_test TO askwell_sandbox_readonly;
GRANT USAGE ON SCHEMA public TO askwell_sandbox_readonly;
GRANT SELECT ON payments TO askwell_sandbox_readonly;
SQL
```

**You should see:** `CREATE TABLE`, `INSERT 0 1`, three `GRANT`s.

```
grep ^SANDBOX_READONLY_PASSWORD .env
```

Note the readonly password.

### 6. Connect to it, by clicking

Still on **Add a source**, in the **Connect a database** section: Engine `PostgreSQL`, Host
`sandbox`, Port `5432`, Database `stepevents_test`, User `askwell_sandbox_readonly`, Password
(from step 5). Click **Connect**.

**You should see:** a queued/ready confirmation naming `stepevents_test`; the library shows it
as **Ready** after a few seconds. The corpus is now hybrid — one document, one connected
database — which is what makes `run_tool_loop` the path this ticket touches (`_has_hybrid_
sources` in `api/src/askwell/ask.py`).

---

## 1. A hybrid question's tool-call labels arrive live, one per call, not in a post-loop burst

### 7. Ask a question that plausibly needs both the document and the database

Go to **Ask**. In the composer, type:

```
Using both the agreement and the database, is Meridian Corp actually being paid within the
required 30 days?
```

Click **Ask** (or press Enter). Watch the working area under the composer as the answer
generates, and keep an eye on the Network tab.

**You should see, while it is working:** one or more `"Called {tool}."` labels appear next to
each other, joined by " · " (e.g. `Called document_search. · Called database_query.`), building
up progressively rather than all appearing in one instant at the moment the answer starts
streaming. This is the visible difference from before this ticket: a label for a call now lands
the moment that call itself returns, not after every call in the turn has already finished.

### 8. Confirm from the Network tab that the labels are not simultaneous

In the developer tools' Network tab, find the request to `/ask` (or `/ask/{id}/stream`) and open
its response/EventSource view (in Chrome: the "EventStream" tab of that request; in Firefox:
the response body updates live). **You should see:** the `step` events for each `Called {tool}.`
label carry different arrival times in the panel — not one bunched instant right before the
`done` event, which is what the old, pre-loop-generic-label-plus-post-loop-burst shape would
have produced.

**If the model only used one tool** (a small model may decide the document alone answers it, or
vice versa): re-ask, naming the tool you want it to prefer, e.g. "Check the `payments` table in
the connected database, and separately check what the agreement says the terms should be" — or
accept a single-call turn and confirm just the one label appears, then continue to step 9
regardless.

### 9. Confirm the trace recorded one `tool`-kind step per call actually made

```
scripts/dev.sh psql -c "SELECT id FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
```

Note the `id` as `$MSG_ID`.

```
scripts/dev.sh psql -c "
SELECT step->>'tool', step->>'deduplicated', step->>'outcome'
FROM messages, jsonb_array_elements(trace->'steps') AS step
WHERE id = '$MSG_ID' AND step->>'kind' = 'tool';
"
```

**You should see:** one row per tool call the model actually made this turn (`document_search`
and/or `database_query`), `deduplicated` reading `false` for each (a repeated identical call
within the same turn would show `true` and would not have produced its own live label — see
`_emit_tool_call_step`'s comment: the observer only fires for a call actually dispatched). The
row count here should match the number of distinct `Called {tool}.` labels you saw in step 7.

---

## 2. `"start"` is deliberately not surfaced yet — confirm this is the shipped behaviour, not a bug

### 10. Re-read the wiring

```
grep -n "_emit_tool_call_step" -A 12 api/src/askwell/ask.py
```

**You should see:** the function returns immediately when `event.phase != "end"`, with a
comment naming issue #420 and `M5-LOOP-FE-118` as why — the frontend has no phase discriminator
to render a `"start"` label distinctly from an `"end"` label yet, so only `"end"` is emitted to
avoid doubling every visible step. If you saw only one label per tool call in §1 (not two, one
for start and one for end), that is this behaviour working as shipped, not a defect to report.

---

## 3. The observer's full start/end contract, proven directly against the real loop code

The browser can only ever show what `ask.py` chooses to surface (§2) — the ticket's own
Acceptance Criteria (N starts and N ends, a parallel batch's starts all preceding its ends, an
observer failure swallowed, no-observer behaviour unchanged) are properties of `run_tool_loop`
itself. This section drives it directly, the same shape `M5-LOOP-BE-116.md`'s own "nothing
gathered" edge case and `M5-LOOP-BE-117.md`'s §5 used for cases a real model cannot reliably be
steered into on demand. No model or stack access is needed for this section.

### 11. Run the scripted repro inside the API container

```
scripts/dev.sh run python - <<'PY'
import asyncio
import json
from typing import Any, cast
from unittest.mock import AsyncMock

from askwell.agent import loop as loop_module
from askwell.agent.loop import ToolCallEvent, run_tool_loop
from askwell.agent.tools import ToolError, ToolErrorCode, ToolResult, ToolStep
from askwell.inference.client import Completion


def ok_step(tool: str, arguments: dict[str, Any]) -> tuple[ToolResult, ToolStep]:
    return (
        ToolResult(content={"ok": True}, truncated=False, error=None),
        ToolStep(
            kind="tool",
            tool=tool,
            arguments=arguments,
            duration_ms=1,
            outcome="ok",
            truncated=False,
            detail={},
            injection_flagged=False,
            injection_patterns=(),
        ),
    )


class FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)

    async def generate(self, prompt: str, **kwargs: Any) -> Completion:
        text = self.responses.pop(0)
        return Completion(text=text, tokens=len(text.split()))


class StaggeredTool:
    """Two calls, dispatched together, that finish in the OPPOSITE order to
    how they were dispatched — proving interleaving is observed per call,
    not reconstructed from the batch finishing."""

    async def __call__(self, name: str, arguments: dict[str, Any], *, session, settings, client):
        delay = 0.05 if name == "document_search" else 0.0
        await asyncio.sleep(delay)
        return ok_step(name, arguments)


async def main() -> None:
    loop_module.call_tool = StaggeredTool()  # type: ignore[assignment]
    events: list[tuple[str, str, str | None]] = []

    def observer(event: ToolCallEvent) -> None:
        events.append((event.phase, event.tool, event.outcome))

    client = FakeClient(
        [
            json.dumps(
                {
                    "type": "tool_calls",
                    "calls": [
                        {"tool": "document_search", "arguments": {"query": "terms"}},
                        {"tool": "database_query", "arguments": {"question": "payments"}},
                    ],
                }
            ),
            json.dumps({"type": "answer", "text": "Paid on time [1][2]."}),
        ]
    )

    result = await run_tool_loop(
        cast(Any, None),
        cast(Any, None),
        cast(Any, client),
        question="Is Meridian Corp paid on time?",
        on_tool_call=observer,
    )

    phases = [phase for phase, _, _ in events]
    assert phases == ["start", "start", "end", "end"], phases
    assert result.stopped_reason == "answered"
    print("OK: both starts arrived before either end, even though database_query finished first")

    # No observer: behaviour is unchanged.
    client2 = FakeClient(
        [
            json.dumps(
                {"type": "tool_calls", "calls": [{"tool": "document_search", "arguments": {"query": "terms"}}]}
            ),
            json.dumps({"type": "answer", "text": "Net 30 [1]."}),
        ]
    )
    result2 = await run_tool_loop(
        cast(Any, None), cast(Any, None), cast(Any, client2), question="What are the terms?"
    )
    assert result2.text == "Net 30 [1]."
    print("OK: with no observer, the loop result is unchanged")

    # An observer that raises is swallowed, and the turn still completes.
    def bad_observer(event: ToolCallEvent) -> None:
        raise RuntimeError("boom")

    client3 = FakeClient(
        [
            json.dumps(
                {"type": "tool_calls", "calls": [{"tool": "document_search", "arguments": {"query": "terms"}}]}
            ),
            json.dumps({"type": "answer", "text": "Net 30 [1]."}),
        ]
    )
    result3 = await run_tool_loop(
        cast(Any, None),
        cast(Any, None),
        cast(Any, client3),
        question="What are the terms?",
        on_tool_call=bad_observer,
    )
    assert result3.stopped_reason == "answered"
    print("OK: an observer that raises is swallowed, and the turn still completes")

    # A failed call still fires an end event, marked with its real outcome.
    class FailingTool:
        async def __call__(self, name, arguments, *, session, settings, client):
            return (
                ToolResult(content=None, truncated=False, error=ToolError(ToolErrorCode.NO_CONNECTION, "No connected database.")),
                ToolStep(
                    kind="tool", tool=name, arguments=arguments, duration_ms=1, outcome="no_connection",
                    truncated=False, detail={}, injection_flagged=False, injection_patterns=(),
                ),
            )

    loop_module.call_tool = FailingTool()  # type: ignore[assignment]
    events4: list[tuple[str, str | None]] = []

    def observer4(event: ToolCallEvent) -> None:
        events4.append((event.phase, event.outcome))

    client4 = FakeClient(
        [
            json.dumps(
                {"type": "tool_calls", "calls": [{"tool": "database_query", "arguments": {"question": "x"}}]}
            ),
            json.dumps({"type": "answer", "text": "Could not check that."}),
        ]
    )
    result4 = await run_tool_loop(
        cast(Any, None),
        cast(Any, None),
        cast(Any, client4),
        question="Is the database up to date?",
        on_tool_call=observer4,
    )
    assert events4 == [("start", None), ("end", "no_connection")], events4
    assert result4.stopped_reason == "answered"
    print("OK: a failed call still fires an end event marked with its real outcome")


asyncio.run(main())
PY
```

**You should see:** four `OK:` lines — the same properties `api/tests/test_loop.py`'s
`test_a_batchs_starts_all_arrive_before_any_of_its_ends`,
`test_with_no_observer_the_loop_result_is_unchanged`,
`test_an_observer_that_raises_is_swallowed_and_the_turn_completes` and
`test_a_failed_call_still_fires_an_end_event_marked_failed` already assert in the automated
suite, reproduced here against the real, un-mocked `run_tool_loop` rather than trusted from the
test file alone.

---

## 4. Clean up

```
podman compose down -v
rm -rf ~/askwell-test
```

**You should see:** no error.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not demonstrable in this environment:

- **`"start"` events reach `run_tool_loop`'s observer but are never rendered.** `M5-LOOP-FE-118`
  (Out of Scope here) is what gives the frontend a phase discriminator to show a call as
  "in progress" the moment it starts rather than only once it ends. Until then, a call in
  flight looks identical to no call having started yet.
- **Whether a real model calls more than one tool in the same turn is not guaranteed.** §1's
  fallback guidance exists because a small local model's own choice of which tools to use, and
  how many, is not something a typed question can force byte-for-byte — the same caveat
  `M5-LOOP-BE-115.md`/`-116.md`/`-117.md` already recorded.
- **The exact wall-clock gap between two parallel calls' end labels is not something the browser
  lets you measure precisely** — the Network tab's timing view is good enough to see the labels
  are not simultaneous, but §3's scripted repro is the actual proof of the ordering contract
  (`N` starts before any of `N` ends), not §1.
- **Citations for a loop-answered turn** are a separate, already-tracked follow-up (issue #407)
  and are not exercised here.
- **No live cold-start verification was performed while writing this document** — it was
  authored by reading `api/src/askwell/agent/loop.py`, `api/src/askwell/ask.py` and
  `api/tests/test_loop.py` directly, following the same gap several prior tickets in this epic
  recorded (`docs/BRAIN.md`'s `M5-LOOP-BE-115`/`-116`/`-117` entries, issue #376) — no inference
  bridge serving a model in that environment. Run this document against a real cold start
  before relying on it as proof rather than a script.
