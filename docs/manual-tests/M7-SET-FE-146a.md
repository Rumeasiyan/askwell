# Manual test — M7-SET-FE-146a, persistent marker on answers from an unvalidated model

**Ticket:** `M7-SET-FE-146a` — every answer produced while a user-supplied model is active carries a persistent, unobtrusive marker naming that citations and abstention are unverified for it; an answer produced by a shipped default never carries it; the marker does not retroactively change once written.
**Version under test:** `0.7.22`
**Time:** about 25 minutes.
**Who can run it:** a browser, the running stack, and a terminal for one step that substitutes for UI that does not exist yet (see below). No real GGUF model file is needed — the substitution writes the same database row a real swap would.

**What is being checked.** `askwell.model_select.active_model_identity` is read once, at question time, into `messages.model_identity` (`api/src/askwell/ask.py`), returned on the `done` SSE event from all three answer paths and on reconnect/replay, carried into `AskTurn.modelIdentity` (`web/components/ask/ask-state.tsx`), and rendered by `web/components/ask/ask-screen.tsx`'s `isUnvalidatedModelTurn` as a compact badge on a collapsed turn's row and a full sentence beside a live or expanded one — never dismissible, never an alarm colour.

**Where this stops on purpose — read before you report anything as broken.** `M7-SET-FE-146`, the settings screen with the actual swap-model UI (**Settings → Model and speed**), is not merged into `main` as of this version (open PR #634, branch `feat/m7-set-fe-146`). There is no button anywhere in this build that swaps the active model. Step 9 below substitutes a direct database write for the settings-screen swap the ticket's own testing notes describe — the same substitution the implementing session used, recorded in `docs/BRAIN.md`'s `0.7.22` entry. Everything downstream of the swap (the marker itself) is real product behaviour rendered by the real browser; only the *mechanism for triggering* the swap is not the shipped one.

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

You will need one plain-text document to add as a source — any `.txt` or `.pdf` a few paragraphs long, containing a fact you can ask about (for example, a sentence stating a retention period or a number).

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

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait about thirty seconds.

### 3. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 4. Open Askwell

Open a browser at:

```
http://127.0.0.1:8000
```

**You should see:** the **Ask your own material** first-run page.

---

## Part A — an answer from the shipped default carries no marker

### 5. Add a source

Click **Add a source**, add your prepared document, and wait for it to leave the queue (its status stops reading "indexing").

### 6. Go to Ask

Click **Ask** in the left strip.

**You should see:** the composer, with the added source available to answer from.

### 7. Ask a question your document answers

Type a question whose answer is the fact in your document, and submit it.

**You should see:** the turn complete with an answer and at least one citation to your document. Look at the turn's row (once it collapses, or immediately if you leave it expanded): **no "Unverified model" badge and no grey sentence about unverified citations and abstention anywhere in the turn.** This is the shipped default — `active_model_identity` reports `"source": "shipped"`, and `isUnvalidatedModelTurn` is false for it.

Note the wording of the answer or the first few words of the question — you will need to find this exact turn again in Part D.

---

## Part B — activate a user-supplied model (substituting for the missing settings UI)

### 8. Open a database shell

```
scripts/dev.sh psql
```

**You should see:** a `psql` prompt connected to Askwell's own database.

### 9. Write the same setting a real swap would write

```sql
INSERT INTO settings (key, value, updated_at)
VALUES ('model.active_source', 'user_supplied', now())
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
```

**You should see:** `INSERT 0 1`.

This is `askwell.model_select.select_user_model`'s own `SETTING_ACTIVE_SOURCE` write, made directly because no browser control performs it yet. Leave `model.user_model_path` unset — `active_model_identity` falls back to the running inference process's own model name for `display_name` in that case, which is fine for this test; only `source` matters to the marker.

Type `\q` to leave `psql`.

---

## Part C — a new answer carries the marker

### 10. Ask a second question

Back in the browser, ask a different question your document answers (or the same one again).

**You should see:** the turn complete as before, but this time:

- While the turn is live (or once expanded), a grey sentence appears beneath the answer reading, in full:

  > This answer came from a model Askwell hasn't tested. Citations and "I don't know" (abstention) are behaviours Askwell verifies for the models it ships; with your own model, they are not guaranteed.

  Not "unverified model" alone — it names citations and abstention specifically, as the acceptance criteria require.
- Once the turn collapses, its row carries a small triangular-warning-icon badge reading **Unverified model**, sitting in the same row as the source-count badge.
- The marker is **not** in an alarm colour (not red) and has **no close button, no dismiss control, and no way to hide it** — try clicking directly on the badge and the sentence; neither responds as a dismiss action.

### 11. Collapse and re-expand this second turn

Click the turn's collapsed row to expand it, then click again to collapse it.

**You should see:** the **Unverified model** badge is present in both the collapsed row and, on expansion, the full sentence reappears beside the answer — it survived the collapse/expand cycle rather than being computed only once at render time.

---

## Part D — the marker does not apply retroactively

### 12. Find your first turn from Part A again

Scroll up (or use the same page — it is the same conversation) to the turn you asked in step 7, before the model swap.

**You should see:** that turn still has **no** "Unverified model" badge and **no** unverified-model sentence, even though the model is currently set to `user_supplied`. The marker was captured once, at question time, into that turn's own stored `model_identity` — it is not recomputed against whatever model happens to be active now.

---

## Part E — reverting clears the marker for new answers only

### 13. Revert the setting

```
scripts/dev.sh psql
```

```sql
UPDATE settings SET value = 'shipped', updated_at = now() WHERE key = 'model.active_source';
```

Type `\q`.

### 14. Ask a third question

**You should see:** this new turn carries **no** marker — `active_model_identity` now reports `"shipped"` again.

### 15. Look at the second turn (from Part C) once more

**You should see:** it **still** carries the "Unverified model" badge and sentence. Reverting the active model clears the marker only for turns asked afterward; it does not retroactively unmark a turn that was really answered by the unvalidated model.

---

## Known gaps

- **The real settings-screen swap UI (`M7-SET-FE-146`) does not exist in this build.** There is no way to reach **Settings → Model and speed**, browse for a model file, or see the "this model has not been tested" warning stated at swap time (`docs/ux/settings.md` §2) — that entire screen is unmerged (PR #634). Step 9's direct database write is a deliberate, documented substitution for it, not a defect.
- **No eval is run against the user-supplied model**, by design (this ticket's own Out of Scope) — the marker states that citations and abstention are unverified, it does not measure them.
- **The size warning for a model bigger than the probed hardware** (`SwapOutcome.size_warning`, `M7-SET-BE-145a`) has no surface to render it yet, since that surface is also part of `146`.
- **No real GGUF model file was loaded.** `display_name` in this walkthrough falls back to whatever the currently-running inference process reports (or `null` if none is loaded and the turn would abstain/fail before reaching a model at all) — a real swap through `146`'s UI, once merged, should be re-walked to confirm `display_name` shows the user's actual filename.
