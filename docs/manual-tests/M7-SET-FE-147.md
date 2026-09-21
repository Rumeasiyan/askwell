# Manual test — M7-SET-FE-147, Settings: privacy and security

**Ticket:** `M7-SET-FE-147` — the privacy-and-security section of Settings: the passphrase
control, network activity stated as a fact with the proxy's live count, and connected databases
with their read-only status.
**Version under test:** `0.6.5` (check `cat VERSION` — bump this line if it has moved on).
**Time:** about 25 minutes.
**Who can run it:** anyone who can open a browser and a terminal (two steps need
`podman compose exec`/`stop` to exercise the proxy directly — see "Known gaps" if unavailable).

**What is being checked.** `web/components/settings/privacy-security.tsx`,
`web/components/settings/passphrase.tsx`, `web/components/settings/network-activity.tsx`,
`web/components/settings/connections.tsx`, `web/lib/passphrase.ts`, `web/lib/network.ts` against
`GET/POST /settings/passphrase*` (`api/src/askwell/security` — `M7-SEC-BE-151`) and
`GET /network` (`api/src/askwell/network.py`).

---

## Before you start

Bring the stack up with the built frontend, since the API serves `web/out`, not live source:

```
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh web-build
podman compose restart api
```

---

## Part A — cold start, reaching the section by clicking

### 1. Open the application

In a browser, go to `http://localhost:8000/`.

**Expect:** the Ask screen loads. The left rail shows **Ask**, **Library**, and **Settings**
among its entries.

### 2. Open Settings

Click **Settings** in the left rail.

**Expect:** the Settings page loads with headings including **Hardware profile**,
**Retrieval threshold**, and **Storage**. Scroll down to **Privacy and security**.

**Expect:** the section shows three subsections in order: **Passphrase**, **Network activity**,
**Connected databases**. There is no fourth subsection and nothing labelled "web search" — that
control must never exist on this screen.

---

## Part B — passphrase control

### 3. Read the off state

Under **Passphrase**, on a fresh install.

**Expect:** text reading "Off. A stolen laptop is readable as-is. Setting a passphrase encrypts
your library and stored credentials." and a **Set a passphrase** button.

### 4. Open the set-passphrase form

Click **Set a passphrase**.

**Expect:** a warning box reading "There is no recovery. Losing this passphrase means losing
the library — Askwell cannot decrypt it for you, on this machine or any other." appears above
the input fields, not in a dialog that could be dismissed unread. Two password fields (new,
confirm) and a checkbox "I understand there is no recovery" appear, plus **Set passphrase**
(disabled) and **Cancel**.

### 5. Type a weak passphrase

In the first field, type `abc`.

**Expect:** after a short pause, a strength line appears reading "Strength: Weak" with feedback
text below it. **Set passphrase** stays disabled — the button requires the server's own
`meets_minimum` to be true, not just non-empty fields.

### 6. Type a strong passphrase that does not match confirmation

Clear the first field and type a longer passphrase, e.g. `correct horse battery staple 2026`.
Leave **Confirm passphrase** empty, then type something different into it, e.g. `correct horse
battery staple 2025`.

**Expect:** strength improves (e.g. "Good" or "Strong"). A red "Does not match." line appears
under the confirm field. **Set passphrase** stays disabled.

### 7. Match the confirmation but skip the checkbox

Make **Confirm passphrase** identical to the first field. Leave the acknowledgement checkbox
unticked.

**Expect:** the "Does not match." line disappears. **Set passphrase** is still disabled — the
checkbox is a real gate, not decorative.

### 8. Acknowledge and submit

Tick "I understand there is no recovery," then click **Set passphrase**.

**Expect:** the button reads "Setting…" briefly, then the form closes and the section now
reads "On. The library and stored credentials are encrypted with it." with **Change
passphrase** and **Remove passphrase** buttons. No confirmation banner is required beyond this
state change — record if there is or is not one so it is not later mistaken for a defect.

### 9. Change the passphrase

Click **Change passphrase**. Enter the current passphrase, a new one that meets the minimum, and
matching confirmation, then submit.

**Expect:** "Passphrase changed." appears and the fields clear. State remains "On."

### 10. Remove the passphrase

Click **Remove passphrase**. Read the warning ("Removing it decrypts the library with this
machine's own key again — a stolen laptop becomes a data breach again."), enter the current
passphrase, and submit.

**Expect:** a confirmation message from the server appears, and the section reverts to the
**Off** state from step 3, ready to be set again.

---

## Part C — network activity

### 11. Read the statement on a machine that has made no permitted requests

Look at **Network activity**.

**Expect:** a sentence of the shape "**0** outbound requests permitted · **0** refused,
measured by the egress proxy itself. Not a setting — this is what actually happened." There is
no toggle, switch, or checkbox anywhere in this subsection — the whole point of the ticket is
that this is a statement, not a control.

### 12. Trigger a refused request

Exec into a container that routes through the proxy and try to reach something external:

```
podman compose exec api curl -s -o /dev/null -w "%{http_code}\n" http://example.com/
```

**Expect:** the curl fails or returns a non-2xx status (the proxy refuses it — C1's "no
outbound network calls" holds even from inside the stack).

### 13. Confirm the refusal is reflected

Reload the Settings page (or just the Privacy and security section) in the browser.

**Expect:** the **refused** count under Network activity has increased by (at least) one from
step 11's reading. Below the statement, a line reads "Most recent refusals (of `<N>` kept):"
followed by a list entry naming a service and destination (e.g. `api → example.com`), shown
plainly rather than hidden.

### 14. Confirm the proxy-unavailable state does not read as zero

Stop the proxy:

```
podman compose stop egress-proxy
```

Reload Settings.

**Expect:** the **Network activity** subsection no longer shows a permitted/refused count.
Instead it reads "Unavailable — the egress proxy's counters could not be read." followed by the
server's own reason and "This is not the same as zero; it means the figure is unknown right
now." Restart the proxy afterwards:

```
podman compose start egress-proxy
```

---

## Part D — connected databases

### 15. Read the empty state

With no database connected (the default), look at **Connected databases**.

**Expect:** text stating none are connected, explaining what connecting one would let Askwell
do, that it only asks for read-only credentials and refuses anything that can write, and an
explicit "0 connected databases" — stated separately from the network-activity figure above, per
this section's own point that the two must never be confusable.

### 16. Connect a database (if one is available)

From **Library** → **Add a source** → **Connect a database**, connect a Postgres instance you
control (a disposable local one is fine), using read-only credentials.

**Expect:** back in Settings → Privacy and security → Connected databases, a count line reads
"1 connected database" and a card lists its name with "Read access confirmed · write access
refused if found."

---

## Known gaps

Do not report these as defects — they are out of scope for this ticket or not practical to
exercise on every run:

- **Web-search escalation history is not shown anywhere in this section.** `M6.5` has not
  landed. `network-activity.tsx`'s own comments describe where it will land (named per
  destination, inside this same subsection) once it does — there is nothing to test yet, and
  there must never be a toggle for it.
- **Connected databases' "read-only" claim is not independently probed by this walkthrough.**
  `docs/ux/settings.md` §4 is explicit that this status is honestly "not yet checked" until
  `M4-CONN-SEC-097`'s write probe exists and actually ran for that connection — this test only
  confirms the label renders, not that a write attempt was independently verified to fail.
- **Step 12's refusal was produced with `curl` from inside the `api` container**, not by
  driving a real product feature into refusing — there is no in-product action that currently
  attempts egress on purpose to refuse. If a future ticket adds one (e.g. a disabled online-AI
  control attempting a call), prefer that as a more realistic trigger.
- **Passphrase-locked state (`status.locked === true`)** — "a passphrase is set for this
  install but this session has not unlocked it yet" — was not exercised here, since unlocking
  and session/lock mechanics belong to `M7-SEC-BE-151` and are not reproducible by clicking
  alone within this walkthrough.
- **Exact refusal-list cap (`recent_capped_at`) was not driven to its limit.** Producing enough
  distinct refusals to fill the kept list was not attempted; the single refusal from step 12 is
  enough to confirm the list renders and is labelled honestly.
