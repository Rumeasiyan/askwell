# Manual test — M7-FIX-FE-174, the online offer describes the model that exists

**Ticket:** `M7-FIX-FE-174` — the abstention surface's "Ask a larger model" offer read
"uses credits · you have none", a paywall left over from the credit tier dropped
2026-09-23 (`docs/decisions.md`). Rewritten to name the real mechanism — a provider key the
user supplies, currently unset because M8 has not built anywhere to set one yet.

**Version under test:** `0.7.24`
**Time:** about 20 minutes, with a native inference process running.

**What is being checked.** `web/components/ask/ask-screen.tsx`'s `EscalationOffer` — one
of its three `EscalationOption`s, the "Ask a larger model" cost caption — and the two docs
that specify it: `docs/ux/web-search.md` §2 and `docs/ux/settings.md` §9. This is a copy-only
ticket: the offer's layout, the other two options, and the abstention text above it are all
`M6.5-WEB-FE-186`'s and are only re-confirmed here, not re-tested in full — that walkthrough
covers keyboard order, narrow-window wrapping, and the web/add-source options in depth.

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
Leave `ASKWELL_WEB_SEARCH_PROVIDER` blank — this ticket does not touch the web-search path.

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

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as
started. Wait about thirty seconds.

### 3. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 4. Start native inference

```
scripts/dev.sh inference
```

Leave this running in its own terminal. **You should see:** the process report a loaded
model and stay running. If no model is configured in this environment, skip to Part B and
read "Known gaps" — the offer only appears after a real abstention, which needs a real
retrieval pass.

### 5. Open Askwell

Open a browser at:

```
http://127.0.0.1:8000
```

**You should see:** the **Ask your own material** first-run page.

### 6. Add a source with a narrow, checkable topic

Click **Add a source**. Add one file about a specific, narrow topic (e.g. a single-page PDF
about a return policy). Wait for it to reach `ready` — its row in the ingest progress list
stops showing a spinner.

### 7. Return to Ask

Click **Ask** in the left strip (or the Askwell wordmark).

---

## Part A — the rewritten offer

### 8. Ask a question the corpus does not cover

Type something clearly unrelated to what you added (e.g., if you added a return policy, ask
"What was our Q3 revenue in the Nairobi office?"). Press **Enter**.

**You should see:** the abstained state — situation, proof of search, next action, rendered
at once, not streamed — followed by three boxed options below it.

### 9. Read the middle option, "Ask a larger model," specifically

**You should see:**

- The label reads **"Ask a larger model"**, unchanged.
- The cost caption beneath it reads **"your own API key · not set up yet"** — not "uses
  credits", not "you have none", and no number or balance anywhere in the caption.
- The button looks visibly disabled (dimmer, roughly 60% opacity), same as before.

### 10. Click it

**You should see:** nothing happens — no network request, no navigation, no change to the
caption. Same inert no-op as before this ticket; only the words changed.

### 11. Confirm the other two options are untouched

**You should see:** **Search the web** still reads "sends your question out · this question
only", and **Add a source instead** still reads "keeps the answer in your own material" —
this ticket did not touch either.

### 12. Confirm the abstention text itself is untouched

Re-read the three abstention lines above the offer. **You should see:** exactly the wording
`M2-ABSTAIN-FE-055` produced — situation, proof of search, next action — with no mention of
credits, keys, or the offer below it. The abstention is the answer; the offer is separate.

---

## Part B — grep confirms no stray copy survives

### 13. Search the frontend and docs for the retired wording

```
grep -rn "you have none\|uses credits" web/ docs/ux/
```

**You should see:** no output — nothing under `web/` or `docs/ux/` still says either phrase.

### 14. Read the settled decision in Settings

Click **Settings** in the left strip, scroll to the **Open** section near the bottom (§9).

**You should see:** a third settled item, dated 2026-09-23, naming `M7-FIX-FE-174` and
stating the offer now names a provider key rather than credits, with §3 flagged as still
describing the old credit flow and tracked separately as issue #658.

---

## Known gaps

- **No settings surface to actually set a provider key exists yet.** M8 is unbuilt, so
  step 9's "not set up yet" cannot be followed anywhere — there is no destination to click
  through to. The ticket's stated scope was the offer's wording and the two doc sections, not
  building that destination.
- **`docs/ux/settings.md` §3 still describes the pre-2026-09-23 credit flow** (balance,
  purchase, spending limit) and was deliberately left alone — out of this ticket's scope,
  filed as issue #658 for whoever designs M8's real key storage.
- **No component test exercises this string.** This repo's frontend `test` script
  (`web/package.json`) runs `node --test` over `lib/*.ts` only; there is no `.tsx`
  component-rendering harness anywhere in the repo. This walkthrough plus the grep in Part B
  are the only checks.
- **Whether the offer appears at all depends on real retrieval and a real model.** Without
  `scripts/dev.sh inference` running, this document cannot be exercised past step 7.
- **A partial answer's named gap shows the same offer** (`M6.5-WEB-FE-186` Part G) — not
  re-walked here since this ticket changed only the caption, not where the offer renders.
