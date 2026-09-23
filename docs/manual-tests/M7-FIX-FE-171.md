# Manual test — M7-FIX-FE-171, the provenance margin mounts on Ask only

**Ticket:** `M7-FIX-FE-171` — the right-hand provenance margin renders on the Ask screen only;
Library, Clarifications, Memory and Settings use the full content width and show no margin copy.
Navigating away from and back to Ask restores the margin, populated, for the live turn.
**Version under test:** `0.7.23`
**Time:** about 15 minutes, no native inference process required (Part C needs one).

**What is being checked.** `web/components/shell/shell.tsx`'s `ShellFrame` — the `isAsk` check
(`pathname === "/"`) that now gates both the `<aside aria-label="Provenance">` mount and the
`LiveLeaderCanvas` mount. No API or data touchpoint beyond routing; this is one conditional in the
shared layout.

**Where this stops on purpose.** No change to the margin's own content, empty-state copy, or
never-collapsible behaviour on Ask — all unchanged from `M1-CITE-FE-044`.

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

### 4. Open Askwell

Open a browser at:

```
http://127.0.0.1:8000
```

Maximise the window, or at least widen it past roughly 1300px — wide enough that the left rail and
the right-hand margin would both be visible on Ask if a margin were present.

**You should see:** either the **Ask your own material** first-run page (if no source has ever
been indexed), or the Ask screen directly. If you land on first-run, click through to add a source
so the rail is available, then continue below. Either way, note whether the right-hand margin
column is present on whichever screen you land on.

---

## Part A — the margin appears on Ask, and only there

### 5. On the Ask screen (click **Ask** in the left rail if you are not already there)

**You should see:** a right-hand column, roughly 300px wide, running the full height of the
content area, separated from the centre column by a vertical rule. With no question asked yet, it
shows its empty-state copy: **"Sources appear here, beside the claims they support."**

### 6. Click **Library** in the left rail

**You should see:** the right-hand margin column is gone. The centre content area now runs the
full remaining width — the page does not just leave blank space where the margin was, the content
column itself widens to fill it. No margin copy anywhere on the page.

### 7. Click **Clarifications** in the left rail

**You should see:** the same full-width layout as Library — no margin column. This is the screen
the ticket calls out as actively misleading before the fix: the margin's Ask-only copy ("sources
appear here, beside the claims they support") no longer appears next to cards on this screen that
already carry their own source evidence.

### 8. Click **Memory** in the left rail

**You should see:** the same full-width layout, no margin column.

### 9. Click **Settings** in the left rail

**You should see:** the same full-width layout, no margin column. This is the ticket's own example
scenario — a full-width settings page, not a narrow one beside an empty column.

---

## Part B — the margin returns, populated, on navigating back

### 10. Click **Ask** in the left rail, and ask a question that draws on your indexed source (e.g. "What does this document say?")

Wait for the answer to finish.

**You should see:** the answer in the centre column, and at least one source card in the right-hand
margin, joined to its claim by a leader line (`M1-CITE-FE-043`/`M1-CITE-FE-044` behaviour,
unchanged).

### 11. Click **Settings** in the left rail, then click **Ask** again

**You should see:** no layout flash — no moment where the full-width layout and the three-column
layout both flicker or overlap. Once Ask has rendered, the margin column is back, showing the same
source card(s) from step 10 for the still-live turn, still paired to their claim by a leader.

---

## Part C — hovering and the leader canvas only run on Ask

### 12. On Ask, with the answer from step 10 visible, hover the cited sentence in the centre column

**You should see:** the claim's background raises and its card in the margin raises with a leader
line — the same pairing behaviour as `M1-CITE-FE-044`, confirming `LiveLeaderCanvas` is still
mounted on Ask.

### 13. Navigate to Library, then open the browser's devtools console and confirm no error is logged

**You should see:** no console error. `LiveLeaderCanvas` (which reads the live Ask turn's pairs) is
now unmounted along with the margin — it does not attempt to draw against a page that has no claim
spans or cards.

---

## Part D — narrow-window behaviour is unaffected

### 14. Return to Ask, and drag the browser window narrower, past roughly 1100–1300px

**You should see:** the same reflow `M1-CITE-FE-044` established — the margin column disappears
and its source cards reappear inline, directly beneath the answer text. This ticket does not touch
that behaviour; it is exercised here only to confirm the Ask-only gate did not disturb it.

### 15. While still narrow, click through Library, Clarifications, Memory and Settings

**You should see:** the same full-width layout as Part A on all four — there is no narrow-window
margin to reflow on these screens because none mounts at any width.

---

## Known gaps

- **No component test infra exists in this repo** (`web/package.json`'s `test` script runs
  `node --test` over `lib/*.test.ts` only, and none of those files touch `Shell` or `ShellFrame`).
  This walkthrough is the only place the Ask-only gate is exercised.
- **The "no layout flash" check in Part B (step 11) is by eye.** Nothing in this repo measures a
  layout-shift metric for this transition; a very brief flash on a slow machine would not be
  caught by an automated gate.
- **If no native `llama.cpp` process is available**, Part B step 10 cannot produce a real answer.
  The empty-margin state from step 5 and the full-width checks in Part A (steps 6–9) can still be
  confirmed without inference; skip steps 10–13 and note the gap.
