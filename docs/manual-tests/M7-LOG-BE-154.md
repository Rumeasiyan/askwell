# Manual test — M7-LOG-BE-154, interaction retention window and prune

**Ticket:** `M7-LOG-BE-154` — a rolling retention window on interactions, a prune that only
ever runs after a full-history export already covers the range, and a hash chain that stays
verifiable across the prune boundary because the prune records where it now starts.
**Version under test:** `0.6.8`.
**Time:** about 25 minutes.
**Who can run it:** anyone who can open a browser and a terminal. Setting the window and
clicking the retention control is done through the real settings screen. Seeding aged
interactions, exporting, pruning and verifying are all `curl`/`scripts/dev.sh` — see "Known
gaps" for why: the frontend has no button wired to `/log-export` or `/log-prune` yet.

**What is being checked.** `api/src/askwell/retention.py` (`POST /log-prune`,
`mark_exported_through`, `latest_prune_boundary`), `api/src/askwell/log_budget.py`
(`set_retention_months`'s `confirmed` flag), and `askwell.audit.verify`'s new `start_from`
parameter as used by `askwell-verify`.

---

## Before you start

Bring the stack up with the built frontend, since the API serves `web/out`, not live source:

```
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh web-build
podman compose restart api
```

Confirm the retention window is at its shipped default before starting:

```
curl -s localhost:8000/log-budget/retention | python3 -m json.tool
```

**Expect:** `{"months": 12}` (or whatever was left from a previous session — note the value so
step 2 can restore it).

---

## Part A — cold start, the settings screen shows the real value

### 1. Open the application

In a browser, go to `http://localhost:8000/`.

**Expect:** the Ask screen loads normally.

### 2. Navigate to the retention control

Click **Settings** in the left rail, then find the **Storage** section (scroll if needed) and
its **Interaction retention window** control.

**Expect:** an input showing the current window in months (matching step 0's `curl`), a
**Change retention window** button, and text stating this only sets the window — "Askwell does
not yet prune interactions past this window." That sentence is now wrong (this ticket builds
the prune) — note it under "Known gaps" below rather than treating it as a defect to fix here.

---

## Part B — a window shorter than existing history needs confirmation

### 3. Seed an old interaction

There is no UI path to backdate an interaction's timestamp, so seed one directly:

```
scripts/dev.sh psql -c "
INSERT INTO audit_interactions (id, kind, payload, prev_hash, hash, occurred_at)
SELECT gen_random_uuid(), 'manual_test', '{\"note\":\"seeded, 24 months old\"}'::jsonb,
       COALESCE((SELECT hash FROM audit_interactions ORDER BY occurred_at DESC, id DESC LIMIT 1),
                 repeat('0', 64)),
       repeat('a', 64), now() - interval '24 months';
"
```

**Expect:** `INSERT 0 1`. (The seeded `hash` is a placeholder, not a real chain link — fine for
this part, which only exercises the confirmation gate; Part D reseeds properly for the chain
checks.)

### 4. Try to shrink the window below that interaction's age, through the real screen

Back in **Settings → Storage → Interaction retention window**, change the number to `1` and
click **Change retention window**.

**Expect:** the control shows an error rather than a confirmation, naming that a 1-month
window is shorter than the age of the oldest interaction on record and would make nearly
everything currently stored prunable. The window shown does not change from its prior value.

### 5. Confirm the same request without confirmation is refused at the API too

```
curl -s -X POST localhost:8000/log-budget/retention -H 'content-type: application/json' \
  -d '{"months": 1}' | python3 -m json.tool
```

**Expect:** HTTP body containing `"confirmation_required": true` and an error naming the same
thing. (The screen has no confirmation checkbox yet — see "Known gaps" — so step 4's refusal
is as far as the UI goes; this step and the next show what confirming looks like underneath.)

### 6. Confirm with the flag set

```
curl -s -X POST localhost:8000/log-budget/retention -H 'content-type: application/json' \
  -d '{"months": 1, "confirmed": true}' | python3 -m json.tool
```

**Expect:** `{"months": 1}`.

### 7. Restore a sane window for the rest of this walkthrough

```
curl -s -X POST localhost:8000/log-budget/retention -H 'content-type: application/json' \
  -d '{"months": 12, "confirmed": true}' | python3 -m json.tool
```

**Expect:** `{"months": 12}`.

---

## Part C — prune refuses without a prior export

### 8. Attempt a prune

```
curl -s -X POST localhost:8000/log-prune | python3 -m json.tool
```

**Expect:** HTTP `409`, body containing `"export_offered": true` and an error stating that
interactions older than the window have not all been exported yet, and that exporting comes
first because pruning unexported records destroys them for good. This is the seeded
interaction from step 3 — old enough to be prunable, but nothing has ever been exported.

---

## Part D — export, then a real prune, then verification

### 9. Seed two more interactions with known ages

```
scripts/dev.sh psql -c "
INSERT INTO audit_interactions (id, kind, payload, prev_hash, hash, occurred_at)
SELECT gen_random_uuid(), 'manual_test', '{\"note\":\"old, will be pruned\"}'::jsonb,
       (SELECT hash FROM audit_interactions ORDER BY occurred_at DESC, id DESC LIMIT 1),
       repeat('b', 64), now() - interval '18 months';
"
scripts/dev.sh psql -c "
INSERT INTO audit_interactions (id, kind, payload, prev_hash, hash, occurred_at)
SELECT gen_random_uuid(), 'manual_test', '{\"note\":\"recent, survives\"}'::jsonb,
       (SELECT hash FROM audit_interactions ORDER BY occurred_at DESC, id DESC LIMIT 1),
       repeat('c', 64), now() - interval '1 month';
"
```

**Expect:** `INSERT 0 1` each time. This gives a mix: the step-3 record (24 months) and the
step-9 first record (18 months) are both older than the 12-month window and should be pruned;
the second step-9 record (1 month) should survive. (The `hash` values here are still
placeholders — this part checks the prune's own mechanics and the export gate, not chain
integrity; a chain-verifying prune is Part E, seeded correctly with `compute_hash`.)

### 10. Export the full history

```
curl -s -X POST localhost:8000/log-export -H 'content-type: application/json' -d '{}' \
  | python3 -m json.tool
```

**Expect:** a `201` body with an `id` and `"status"` of `queued` or `running`. Note the `id`.

### 11. Wait for the export to finish

```
curl -s localhost:8000/log-export/<id-from-step-10> | python3 -m json.tool
```

Repeat every few seconds.

**Expect:** `"status"` eventually reads `"done"`, with a `finished_at` timestamp. This is a
**full-history** export (`since` was not set in step 10) — the only kind that advances the
"exported through" marker the prune checks.

### 12. Prune

```
curl -s -X POST localhost:8000/log-prune | python3 -m json.tool
```

**Expect:** a `200` body with `"records_removed"` at least `2` (the two old seeded records —
possibly more if other tickets' manual tests left interactions behind) and a `"cutoff"` roughly
12 months before now.

### 13. Confirm the store actually shrank

```
scripts/dev.sh psql -c "SELECT payload->>'note', occurred_at FROM audit_interactions ORDER BY occurred_at;"
```

**Expect:** the 24-month and 18-month rows from steps 3 and 9 are gone; the 1-month row
("recent, survives") is still there.

### 14. Confirm the prune itself is a decisions record naming the range

```
scripts/dev.sh psql -c "SELECT payload FROM audit_decisions WHERE kind = 'interaction_prune' ORDER BY occurred_at DESC LIMIT 1;"
```

**Expect:** one row with `cutoff`, `records_removed`, and `first_remaining_prev_hash` in the
payload.

---

## Part E — chain integrity across the prune boundary

Part D's seeded records used placeholder hashes, so a naive chain check on them would already
fail for reasons unrelated to pruning. This part seeds a real, correctly-chained sequence to
isolate what pruning specifically does to verification.

### 15. Clear interactions and reseed a real chain, then repeat export→prune

```
scripts/dev.sh psql -c "TRUNCATE audit_interactions;"
scripts/dev.sh psql -c "DELETE FROM settings WHERE key = 'interactions_exported_through';"
```

Seeding a genuinely hash-chained record needs `askwell.audit.compute_hash`, which is not
reachable from `psql`. Use the running API's own question-asking path instead, which writes a
real chained interaction on every turn:

Click **Ask** in the left rail, type a question, and send it. Repeat three times, a few
seconds apart.

**Expect:** three interactions now exist, each with a correctly computed `hash`/`prev_hash`
(this is what `askwell.ask` already does on every turn — nothing new to this ticket).

### 16. Export, then set a window that makes the oldest of the three prunable

```
curl -s -X POST localhost:8000/log-export -H 'content-type: application/json' -d '{}' \
  | python3 -m json.tool
```

Wait for `"status": "done"` as in step 11, then:

```
scripts/dev.sh psql -c "UPDATE audit_interactions SET occurred_at = now() - interval '13 months' WHERE id = (SELECT id FROM audit_interactions ORDER BY occurred_at ASC, id ASC LIMIT 1);"
```

This backdates only the oldest of the three real, correctly-chained interactions past the
12-month window, without touching its hash — the `prev_hash` pointer of the record right after
it now points at a hash the store still legitimately contains, which the next step's prune
will need to sever correctly.

### 17. Prune again

```
curl -s -X POST localhost:8000/log-prune | python3 -m json.tool
```

**Expect:** `"records_removed": 1`.

### 18. Verify the chain

```
podman compose exec api askwell-verify
```

**Expect:** output for the `interactions` store reads intact (no break reported), with the
walk starting from the recorded prune boundary rather than the universal genesis value —
confirmed by contrast with the next step.

### 19. Confirm a naive check (no boundary) would have called this tampering

This is what `askwell-verify` deliberately avoids by reading `latest_prune_boundary` first —
shown here by checking the surviving record's own `prev_hash` against what remains in the
table:

```
scripts/dev.sh psql -c "SELECT id, prev_hash FROM audit_interactions ORDER BY occurred_at ASC LIMIT 1;"
scripts/dev.sh psql -c "SELECT hash FROM audit_decisions WHERE kind = 'interaction_prune' ORDER BY occurred_at DESC LIMIT 1;"
```

**Expect:** the surviving record's `prev_hash` does **not** match any `hash` still present in
`audit_interactions` — it points at the hash of the record deleted in step 17. Nothing in
`audit_interactions` alone explains this; the explanation lives in the `interaction_prune`
decisions record from step 14's query pattern, which is exactly why `askwell-verify` reads it
before walking the chain.

---

## Part F — decisions and memory are never touched

### 20. Compare decisions-store row counts before and after

```
scripts/dev.sh psql -c "SELECT count(*) FROM audit_decisions;"
```

Note the number, then re-run step 17's prune once more (it will find nothing left to prune,
since step 17 already removed the one eligible record):

```
curl -s -X POST localhost:8000/log-prune | python3 -m json.tool
scripts/dev.sh psql -c "SELECT count(*) FROM audit_decisions;"
```

**Expect:** `"records_removed": 0` from the `curl`, and the decisions count unchanged from the
same call's own read — a prune that removes nothing writes no new decisions record (matching
`retention.py`'s `if removed == 0: return` short-circuit), and no existing decisions row is
ever deleted or altered regardless. Memory has no ticket-relevant table to check here — no
code path in `retention.py` references it at all (confirmed by reading the module).

---

## Cleanup

```
curl -s -X POST localhost:8000/log-budget/retention -H 'content-type: application/json' \
  -d '{"months": 12, "confirmed": true}' > /dev/null
```

The seeded/asked interactions from this walkthrough are left in place — they are ordinary
records now, and deleting them by hand would itself look like tampering to the next person who
runs `askwell-verify`.

---

## What was checked against the ticket's acceptance criteria

- Interactions older than the window are prunable after export — Part D, steps 10–13.
- Decisions and memory are never touched — Part F; also implicit throughout (no `audit_decisions`
  row disappears in any part).
- Verification still succeeds after a prune, with the prune boundary recorded — Part E, steps
  18–19.
- Changing the window changes what is prunable — Part B (refusal/confirmation) and the
  12-vs-13-month contrast between Parts D and E.
- Prune attempted without export is refused, with export offered — Part C.
- A window shorter than the age of everything is refused unless confirmed — Part B.
- The prune is a decisions record naming the range removed — Part D, step 14.
- Export before prune, always — Part C and Part D's ordering.

## Known gaps

Do not report these as defects — they are out of scope for this ticket or not practical to
exercise purely by clicking:

- **No settings-screen button calls `/log-export` or `/log-prune`.** `web/components/settings/
  storage.tsx`'s "Export and prune" section is still the disabled, stated entry point built by
  `M7-SET-FE-148`; wiring it to the now-real endpoints is an unclaimed frontend gap
  (`docs/BRAIN.md`, issue #487). Every export/prune step here goes through `curl` because there
  is nothing to click yet.
- **The retention control's own copy is stale.** It still reads "Askwell does not yet prune
  interactions past this window" (Part A, step 2) — true when `M7-SET-FE-148` wrote it, false
  now that this ticket exists. Cosmetic, not a behavioural defect; flagged rather than silently
  worked around.
- **The retention control has no confirmation UI for the "window shorter than existing
  history" case.** Part B's step 4 shows the refusal on screen; there is no checkbox or second
  click to confirm through — that path is only reachable via `curl` (steps 5–6), the same gap
  as above.
- **"Prune interrupted — resumable" is not exercised.** The prune is a single `DELETE` plus one
  `INSERT` inside one transaction (read from `retention.py`) — an interruption mid-prune rolls
  the whole transaction back by Postgres's own guarantee, leaving nothing partially pruned to
  resume from. There is no separate resume code path to test because none is needed; killing
  the API mid-request to prove this live was not attempted, being destructive to a shared
  development stack.
- **Resetting a passphrase-encrypted install's interaction is not covered.** This walkthrough
  ran with no passphrase set. Export's own `acknowledged_decrypted_export` gate
  (`docs/ux/settings.md` §4) is `M7-LOG-BE-155`'s scope, already covered in that ticket's own
  manual test — not re-exercised here.
- **The exact seeded-hash placeholders in Parts C and D are not real chain links.** Those parts
  test the prune's row-counting and export-gate mechanics only; Part E is the one that seeds a
  genuinely computed chain and is the part that speaks to chain-integrity claims.
