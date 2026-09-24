# Manual test — M7-SET-FE-150, Settings → Online AI (before it exists)

**Ticket:** `M7-SET-FE-150`. It covers **Settings → Online AI** before the feature exists. The section is visible and switched off. It explains what online AI will be and that it is chosen per conversation. It says whose key and whose bill it will be, and promises that what leaves the machine will be stated before anything is sent. Pressing the switch gets a plain "not available yet" statement: no form, no waiting list and no email field.

**Version under test:** `0.7.32`. Run `cat VERSION` and update this line if the version has moved on.

**Time:** about 10 minutes.

**Who can run it:** anyone with a browser and a terminal. The terminal is used only to start Askwell. Every Askwell screen is reached by clicking, starting from Askwell's front page. Part D has one optional step that uses the browser's built-in developer tools; skip it if that is unfamiliar.

**What is being checked.** The section is `web/components/settings/online-ai.tsx`. Its wording lives in `web/lib/online-ai.ts`. It has no server side: nothing in it talks to Askwell's API or to anything else.

> **The wording differs from the ticket on purpose.** The ticket says online AI is "paid by credit" and that Askwell "never asks for an API key from another provider". On 2026-09-23 the product changed: the credit tier was cancelled, and online AI will use a key from a provider the person already pays (`docs/decisions.md`, 2026-09-23 and 2026-09-24). The screen follows the decision, not the ticket. **Do not report the key wording as a defect.** Words about credits, buying or a price *would* be a defect.

---

## Before you start

Build the interface and start the stack:

```
cd ~/external/quantum-plus/askwell
scripts/dev.sh web-build
podman compose up -d --force-recreate api
```

**You should see:** the build finishes with no red error text. Compose reports the containers as started.

The `--force-recreate` is needed after a build. The build replaces `web/out`, and an API container that is already running keeps serving the old copy.

---

## Part A — get to Online AI the way a user would

1. Open a **private or fresh-profile** browser window, so no earlier session carries over. Open `http://127.0.0.1:8000`. This is where a user starts. ☐

   **You should see:** either the **Ask** screen with a rail of links down the left side, or, on an install that has never indexed a source, a page headed **Welcome to Askwell**.

2. If you see **Welcome to Askwell**, click **Skip setup** at its top right. ☐

   **You should see:** the **Ask** screen. The left rail shows **Ask**, **Library**, **Clarifications**, **Memory** and **Settings**.

3. Click **Settings** in the left rail. ☐

   **You should see:** a page headed **Settings**, with **Settings** highlighted in the rail.

4. Scroll down past the introduction and the first section, **Model and speed**. ☐

   **You should see:** the **second** section is headed **Online AI**. Directly below it comes **Folders Askwell may read**. If Online AI is anywhere else, or missing, that is a defect.

## Part B — read the section

1. Under **Online AI**, look at the first line. ☐

   **You should see:** a button-like switch labelled **Use online AI**, drawn in grey. Beside it, in small grey text: **Off. Not available yet.** Hovering the mouse over the switch shows a "not allowed" pointer (a circle with a line through it), not the usual hand.

2. Read the part headed **What it will be**. ☐

   **You should see** two paragraphs, in grey:
   - "A larger cloud model, for a question the model on this machine finds too hard. Askwell works completely without it — it is an escape hatch for a hard question, not a tier."
   - "It will be chosen per conversation. A conversation is either local or online, and you switch it yourself. There will be no setting that turns it on everywhere, so there is nothing to forget about."

3. Read the part headed **Your key, your bill**. ☐

   **You should see:** "It will use an API key from a provider you already pay. Askwell sells nothing and takes no part in what it costs — the account, the provider and the bill are yours. The key will be stored encrypted on this machine, never logged and never exported. Nothing on this screen asks for a key today, because there is nothing yet that could use one."

4. Read the part headed **What leaves this machine**. ☐

   **You should see:** "Exactly what leaves this machine will be stated here, and again in the conversation before anything is sent — never after. Until then, nothing leaves."

5. Look over the whole section once more. ☐

   **You should see:** no text box, no drop-down, no checkbox, no email field, no "join the waiting list", no "notify me", and no link to any website. Nowhere does it mention credits, buying, a balance, a spending limit or a price. The only thing you can press is the **Use online AI** switch.

## Part C — try to turn it on

1. Click **Use online AI**. ☐

   **You should see:** the switch does **not** change. It stays grey, and the line beside it still reads **Off. Not available yet.** A new paragraph appears directly underneath: "Online AI is not available yet, so it cannot be turned on. There is nothing to sign up for and no list to join. When it exists it will appear here, still off until you choose it for a conversation." No form, pop-up or new page opens. The page does not jump or reload.

2. Click **Use online AI** three more times. ☐

   **You should see:** nothing changes. The same paragraph stays, shown once, not stacked up three times. The switch never shows "On".

3. **Keyboard.** Reload the page (F5) and scroll back to **Online AI**. The not-available paragraph is gone. Now press **Tab** repeatedly until the **Use online AI** switch has a visible focus outline, then press **Enter**. ☐

   **You should see:** the same not-available paragraph appears, exactly as in step 1. Press **Space** as well: nothing further changes. A keyboard user gets the same answer as a mouse user, not silence.

4. Reload the page once more. ☐

   **You should see:** the section is back to its starting state: **Off. Not available yet.**, with no not-available paragraph. Trying to turn it on is not remembered, and nothing was saved.

## Part D — nothing leaves the machine

1. Scroll down to **Privacy and security → Network activity**. Write down the two numbers on the line "… outbound requests permitted · … refused, measured by the egress proxy". ☐
2. Scroll back up to **Online AI** and click **Use online AI** five times. ☐
3. Reload the page and scroll to **Network activity** again. ☐

   **You should see:** both numbers are the same as in step 1. If either has gone up, check whether update checking is turned on under **About**; that is the only other thing that could move them, and it fires on its own schedule. With update checking off, any change is a defect.

4. **Optional, browser developer tools.** Press **F12** to open the developer tools and choose the **Network** tab. Click the circle-with-a-line icon ("Clear") so the list is empty. Click **Use online AI** a few times. ☐

   **You should see:** the list stays empty. Clicking the switch makes no request of any kind, not even to Askwell itself. Close the developer tools.

5. **Offline.** Disconnect the machine from the network: unplug the cable or turn off Wi-Fi. Reload **Settings** and scroll to **Online AI**. ☐

   **You should see:** the section appears exactly as in Part B, and clicking the switch shows the same not-available paragraph as in Part C. Reconnect the network.

## Part E — in the desktop app (only if the desktop shell is available)

1. Launch the desktop app. If the welcome page appears, click **Skip setup**. Click **Settings** in the rail. ☐

   **You should see:** **Online AI** is the second section, after **Model and speed**, with the same wording as Part B.

2. Click **Use online AI**. ☐

   **You should see:** the same not-available paragraph as in Part C. Nothing opens outside Askwell.

---

## Known gaps

Not built by this ticket. Do not report these as defects.

- **Online AI does not work.** That is the point of this ticket. The working feature, including where the key is entered, is M8 (`M8-KEY-FE-174` fills this same section in).
- **The wording talks about your own key, not credits.** The ticket was written before the 2026-09-23 decision that cancelled the credit tier. The screen follows the decision (`docs/decisions.md`, 2026-09-24 entry for this ticket). The true part of the ticket's old promise is kept: nothing on this screen asks for a key today.
- **No price is shown.** Askwell sells nothing, so there is no price to describe.
- **The exact list of what leaves the machine is not stated.** It is undecided. The section says it will be stated before anything is sent, rather than guessing now.
- **Nothing is saved.** The not-available paragraph disappears on reload. That is expected: there is no setting behind the switch.
- **The introduction at the top of Settings still says "The surface for them arrives in M7."** That text predates this milestone and belongs to the Settings page, not to Online AI.
