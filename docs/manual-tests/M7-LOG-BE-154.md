# Manual test — M7-LOG-BE-154, interaction retention window and prune

**Ticket:** `M7-LOG-BE-154` — a rolling retention window (12 months by default, user-configurable)
for `audit_interactions`, with a prune that only ever removes rows outside the window, refuses
without a covering export, asks for confirmation when it would remove nearly everything, and
records the boundary it deleted through so `askwell.audit.verify` still passes afterward.
**Version under test:** `0.7.2`.
**Time:** about 20 minutes.
**Who can run it:** anyone who can open a browser and a terminal, with `psql` reachable via
`scripts/dev.sh` to backdate seed rows — a fresh install has nothing old enough to prune, and
waiting twelve months is not a manual test.

**What is being checked.** `api/src/askwell/log_prune.py` (`enqueue`, `run_job`,
`POST /log-prune`, `GET /log-prune/{id}`) and the retention-window half of
`api/src/askwell/log_budget.py` (`GET`/`POST /log-budget/retention`) as reached through
`web/components/settings/storage.tsx`'s **Interaction retention window** control, the one part
of this ticket that already has a click-through.

---

## Before you start

Bring the stack up with the built frontend, since the API serves `web/out`, not live source:

```
cd ~/external/quantum-plus/askwell
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh web-build
podman compose restart api
```

Confirm the app is answering:

```
curl -s localhost:8000/health | python3 -m json.tool
```

**Expect:** a 200 response reporting the API healthy.

---

## Part A — cold start, change the retention window by clicking

### 1. Open Settings

In a browser, go to `http://localhost:8000/`. Click **Settings** in the left rail, then find the
**Storage** section.

**Expect:** the page shows **Index size per source**, **Log storage budget**, **Interaction
retention window**, **Export and prune**, and an **At the limit** notice — matching
`docs/ux/settings.md` §5.

### 2. Read the current retention window

Look at the **Interaction retention window** card.

**Expect:** "Current window: 12 months" (the shipped default), an explanatory line that changing
the number only sets the window and "nothing is deleted by changing this number", and an input
plus a **Change retention window** button.

### 3. Change the window to 6 months

Clear the input, type `6`, and click **Change retention window**.

**Expect:** the button reads "Changing…" briefly, then a confirmation line: "Retention window
changed from 12 to 6 months. Recorded in the decisions log. Askwell does not yet prune
interactions past this window — that arrives with a later ticket." — an accurate statement about
the frontend's own reach into this ticket, even though the backend prune below does exist.
"Current window: 6 months" updates above it.

### 4. Reload the page

Refresh the browser tab and look at the Storage section again.

**Expect:** "Current window: 6 months" — the change persisted server-side, not just in the
component's own state.

---

## Part B — seed old interactions and confirm the prune button is still not clickable

There is no click-through for starting a prune yet — the **Export and prune** button on this same
screen is permanently disabled, stating "Not built yet — this is where it will be reached from
once it is." Confirm that honestly before driving the backend directly:

### 5. Look at Export and prune

**Expect:** a greyed **Export and prune** button that does nothing when clicked (or cannot be
clicked at all — a disabled `<button>`), under the text quoted above.

### 6. Seed interactions old enough to prune

The backend logic is exercised the same way `M7-LOG-BE-155`'s manual test drives export: with
`curl`, since nothing in the UI creates a dated interaction on demand. Insert two backdated rows
directly, chained correctly, through `psql`:

```
scripts/dev.sh psql
```

```sql
INSERT INTO audit_interactions (id, kind, payload, prev_hash, hash, occurred_at)
SELECT gen_random_uuid(), 'question_asked', '{"note":"manual test seed"}'::jsonb,
       '0000000000000000000000000000000000000000000000000000000000000000',
       encode(sha256('manual-test-seed-1'::bytea), 'hex'),
       now() - interval '400 days'
WHERE NOT EXISTS (SELECT 1 FROM audit_interactions);
\q
```

If `audit_interactions` already has rows (a real chain from using the app), skip this step and
instead confirm at least one exists older than 6 months with:

```sql
SELECT count(*) FROM audit_interactions WHERE occurred_at < now() - interval '6 months';
```

**Expect:** at least one row. If the count is 0 on a genuinely fresh install, the seed above
inserts one — it will not chain-verify correctly on its own (its hash is a placeholder, not a
real `compute_hash` output), so treat it as disposable scratch data for exercising the refusal
paths in Part C, and use the automated test suite (`test_log_prune.py`) as the source of truth
for chain-correctness — it seeds properly-hashed rows the way `askwell.audit.record` would.

---

## Part C — the two refusals

### 7. Try pruning without an export

```
curl -s -X POST localhost:8000/log-prune -H 'content-type: application/json' -d '{}' | python3 -m json.tool
```

**Expect:** a `400` body with `"export_required": true` and wording that pruning would remove
interactions that have never been exported, and that export must happen first. No job row
created — confirm with:

```
curl -s localhost:8000/log-budget/retention | python3 -m json.tool
```

(this just confirms the API is still healthy; there is no list route for prune jobs to check
against, by the ticket's own scope).

### 8. Cover the window with an export

There is no export UI either (`M7-LOG-BE-155`'s own manual test notes the same gap), so start one
directly:

```
curl -s -X POST localhost:8000/log-export -H 'content-type: application/json' -d '{}' | python3 -m json.tool
```

**Expect:** `201`, a job with `"status"` of `"queued"` or `"running"`. Poll it:

```
export EXPORT_JOB=<paste the id>
curl -s localhost:8000/log-export/$EXPORT_JOB | python3 -m json.tool
```

**Expect:** `"status": "done"` within a few seconds on a dev-sized log.

### 9. Retry the prune now that an export covers it

```
curl -s -X POST localhost:8000/log-prune -H 'content-type: application/json' -d '{}' | python3 -m json.tool
```

**Expect:** one of two outcomes depending on how much of the seeded data is older than the 6-month
window set in step 3:
- If what is prunable is under 90% of everything: `201`, a job with `"status"` and a `"cutoff"`
  about 6 months back from now.
- If nearly everything is prunable (likely true on a small dev install where the only rows are the
  ones just seeded): `400` with `"confirmation_required": true`, `"prunable_count"`, and
  `"total_count"`. Confirm this reads sensibly (prunable close to or equal to total), then retry
  with acknowledgement:

```
curl -s -X POST localhost:8000/log-prune -H 'content-type: application/json' \
  -d '{"acknowledged_nearly_everything": true}' | python3 -m json.tool
```

**Expect:** `201` this time.

### 10. Poll the prune job to completion

```
export PRUNE_JOB=<paste the id from step 9>
curl -s localhost:8000/log-prune/$PRUNE_JOB | python3 -m json.tool
```

**Expect:** eventually `"status": "done"`, a `"pruned_count"` greater than 0, and a
`"boundary_hash"` that is a 64-character hex string, not `null`.

---

## Part D — verify the chain still passes after the prune

### 11. Run the bundled verifier

```
podman compose exec api askwell-verify
```

**Expect:** exit code `0` (check with `echo $?`), and output for `interactions` naming the record
count remaining and "chain intact." — if the deleted rows were at the front of the chain, the
output additionally names that the chain "starts after a prune (pruned through <cutoff>), not at
genesis — expected, recorded in the decisions store." Look for `decisions: ... chain intact.` too
— untouched by the prune, still starting at genesis.

### 12. Confirm the row count actually dropped

```
scripts/dev.sh psql -c "SELECT count(*) FROM audit_interactions;"
```

**Expect:** fewer rows than before step 9 (or the same, if step 9 pruned 0 because nothing was
old enough — re-check against the count you read in step 6).

---

## Part E — decisions and memory are never touched

### 13. Read the decisions store around the prune

```
scripts/dev.sh psql -c "SELECT kind, occurred_at FROM audit_decisions ORDER BY occurred_at DESC LIMIT 5;"
```

**Expect:** an `interaction_prune_enqueued` row (from step 9) and an `interactions_pruned` row
(from the completed job) — the prune's own explanation of itself, never itself pruned.

### 14. Confirm memory is untouched

```
scripts/dev.sh psql -c "SELECT count(*) FROM memory;"
```

**Expect:** the same count as before Part B–D — nothing here deletes from `memory`, and nothing in
this walkthrough wrote to it either, so any non-zero count from prior use of the app should be
unchanged.

---

## Part F — changing the window changes what is prunable

This is the acceptance criterion "changing the window changes what is prunable" — verified here by
reading, rather than by a second full prune cycle, since `test_changing_the_window_changes_what_is_prunable`
in `api/tests/test_log_prune.py` already exercises the two-window sequence end-to-end against a
real database.

### 15. Widen the window back through Settings

In the browser, back on the Storage section, change the retention window input to `24` and click
**Change retention window**.

**Expect:** the confirmation line names 24 months, and any remaining seeded interactions are now
inside the window (they were backdated by 400 days ≈ 13 months, so a 24-month window keeps them).
A subsequent `POST /log-prune` with `{}` would report `prunable: 0` — you can confirm this without
actually pruning again:

```
curl -s -X POST localhost:8000/log-prune -H 'content-type: application/json' -d '{}' | python3 -m json.tool
```

**Expect:** `201` immediately, no export-required refusal — `test_nothing_prunable_needs_no_export_at_all`'s
own reasoning: a window that keeps everything must not demand an export for nothing to prune.

---

## Cleanup

Restore the retention window to its shipped default of 12 months through Settings, and remove any
scratch export/prune jobs are left as rows — there is no delete route, by this ticket's own scope,
so this is a note, not a cleanup step: `export_jobs` and `prune_jobs` rows from this walkthrough
remain in the dev database, which is expected and matches `M7-LOG-BE-155`'s manual test leaving
the same kind of trace.

---

## What was checked against the ticket's acceptance criteria

- Interactions older than the window are prunable after export — Part C, step 9.
- Decisions and memory are never touched — Part E.
- Verification still succeeds after a prune, with the boundary recorded — Part D, step 11.
- Changing the window changes what is prunable — Part A (the click-through) and Part F (the
  effect on prunability).
- Prune attempted without export is refused, with export offered — Part C, step 7.
- A window shorter than the age of everything needs explicit confirmation — Part C, step 9's
  `confirmation_required` branch.
- Prune interrupted and resumed leaves the chain intact — not exercised by hand here, since it
  requires killing the worker mid-transaction; covered by
  `test_a_prune_interrupted_before_the_delete_commits_leaves_the_chain_intact` in
  `api/tests/test_log_prune.py` instead.

## Known gaps

- **No settings-screen entry point for the prune itself.** `web/components/settings/storage.tsx`'s
  **Export and prune** button is permanently disabled and states "Not built yet" — only the
  retention *window* setting (Part A) has a real click-through; starting an export or a prune both
  happen through `curl` in this walkthrough. The frontend ticket to wire this button up is
  unstarted (same gap `M7-LOG-BE-155`'s manual test records, `docs/BRAIN.md`'s "Next" line, issue
  #487 Option 1).
- **No route to list past prune jobs.** `GET /log-prune/{id}` needs the id from the `POST`
  response; there is nothing to browse. Matches the ticket's own scope — a history view is left to
  a settings ticket, same as `log_export.py`.
- **A prune interrupted mid-transaction was not exercised by hand** — see the note under "What was
  checked" above.
- **The seeded row in Part B, step 6's fallback path is not chain-valid** — its hash is a
  placeholder, not `compute_hash`'s real output, so it exists only to exercise the two refusal
  paths in Part C on an otherwise-empty install. It is not a substitute for the properly-hashed
  fixtures `api/tests/test_log_prune.py::_seed_interactions` builds, which is what actually proves
  chain integrity across a prune.
