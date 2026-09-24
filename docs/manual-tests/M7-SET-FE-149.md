# Manual test — M7-SET-FE-149, Settings → About

**Ticket:** `M7-SET-FE-149`. It covers **Settings → About**: the version, the licence, the third-party notices (including the bundled model weights), the source address, reporting a problem, reporting a security problem, and the update-checking control.

**Version under test:** `0.7.31`. Run `cat VERSION` and update this line if the version has moved on.

**Time:** about 20 minutes.

**Who can run it:** anyone with a browser and a terminal. The terminal is used only to start Askwell, to read the repository's version, and — in two clearly marked places — to look at something the screen does not show. Every Askwell screen is reached by clicking, starting from Askwell's front page.

**What is being checked.** The screen is `web/components/settings/about.tsx`. Its wording lives in `web/lib/about.ts`. The licence, notices, support text and security policy are the repository's own `LICENSE`, `NOTICES.md`, `SUPPORT.md` and `SECURITY.md`, copied into the built interface at build time (`web/scripts/copy-notices.mjs`, `web/scripts/copy-support.mjs`). The update-checking control drives `M7-UPDATE-BE-161`'s real setting (`api/src/askwell/update_check.py`).

> **Part F turns update checking on.** While it is on, Askwell is allowed to fetch one small file from `raw.githubusercontent.com`. On an install that has never checked, the first check can happen within the hour. Turning it on also writes a record to the decisions log. Part F turns it off again at the end, which writes a second record. If that matters, run this on a test install.

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

Note the repository's version. You will compare the screen against it:

```
cat VERSION
```

**You should see:** one line, for example `0.7.31`. Write it down.

---

## Part A — get to About the way a user would

1. Open a **private or fresh-profile** browser window, so no earlier session carries over. Open `http://127.0.0.1:8000`. This is where a user starts. ☐

   **You should see:** either the **Ask** screen with a rail of links down the left side, or — on an install that has never indexed a source — a page headed **Welcome to Askwell**.

2. If you see **Welcome to Askwell**, click **Skip setup** at its top right. ☐

   **You should see:** the **Ask** screen, with the left rail showing **Ask**, **Library**, **Clarifications**, **Memory** and **Settings**.

3. Click **Settings** in the left rail. ☐

   **You should see:** a page headed **Settings**. **Settings** is highlighted in the rail.

4. Scroll down past **Model and speed**, **Folders Askwell may read**, **Storage**, **Privacy and security** and **Your data**. The last section is headed **About**. ☐

   **You should see:** under **About**: **Version**, **Licence**, **Source** and **Notices**, then three sub-headings in this order — **Report a problem**, **Security problem**, **Update checking**.

## Part B — version and licence

1. **Version** shows exactly the number `cat VERSION` printed. Not an older number, not an extra suffix. ☐
2. **Licence** reads `Apache-2.0`. ☐
3. Click **Read the licence in full**. ☐

   **You should see:** a box opens below the link, first showing "Reading…" briefly, then the text. It begins "Apache License / Version 2.0, January 2004".

4. Scroll inside that box to the very bottom. ☐

   **You should see:** the copyright line `Copyright 2026 Suseenthiran Arulraj Rumeasiyan`, and the last words are "limitations under the License." Nothing is cut off mid-sentence. The page around the box does not scroll away while you scroll inside it.

5. Click **Read the licence in full** again. ☐

   **You should see:** the box closes.

## Part C — notices, including the bundled model weights

1. Next to **Notices**, click **Third-party notices and licences, including the bundled model weights**. ☐

   **You should see:** a scrollable box. Its first heading is "Third-party notices", followed by **Bundled model weights**.

2. Read the **Bundled model weights** table. ☐

   **You should see:** one row per bundled model, each naming its source and licence. At the time of writing that is eleven rows, among them `Qwen3.5 4B (Q4_K_M)` (Apache-2.0), `Qwen3.5 9B (Q4_K_M)` (Apache-2.0), `bge-m3` (MIT), `bge-reranker-v2-m3` (Apache-2.0), `Whisper small` (MIT), `Kokoro-82M` (Apache-2.0) and the Tesseract OCR entries (Apache-2.0). Every licence is either Apache-2.0 or MIT.

3. Scroll the box to the very end. ☐

   **You should see:** it passes through the Python dependency tables and ends with the JavaScript dependencies. The last row is `yallist | 3.1.1 | ISC`. There is no "…", "show more", or sentence cut off.

   The text is shown as it is written in the file, so tables appear as lines with `|` characters rather than as formatted tables. That is expected.

## Part D — source, reporting a problem, and a security problem

1. Next to **Source**, the address `https://github.com/Rumeasiyan/askwell` is shown as plain text. Beside it are a **Copy address** button and an **Open** link. ☐
2. Click **Copy address**. ☐

   **You should see:** the button's label changes to **Copied**. Paste into any text field (the browser's address bar will do). The pasted text is exactly `https://github.com/Rumeasiyan/askwell`.

3. Under **Report a problem**, read the short line first. It says to read what one maintainer can and cannot answer first, and that it reads without a network. ☐
4. Directly below that, a box is **already open** — you do not have to click anything to see it. It begins "# Support" and "**Askwell is maintained by one person.**". ☐
5. Scroll that box to the end. ☐

   **You should see:** sections headed "Where to go", "What is answered", "What is promised", "What is not promised", "What a good report contains" and "How issues are triaged".

6. Below the box, the line reads "Then open an issue. Include the version above, your platform, your profile and a copied trace." Under it, the address `https://github.com/Rumeasiyan/askwell/issues/new/choose` is shown as text, with **Copy address** and **Open**. ☐

   The support text comes **before** the issue address on the page. That order is the point: the boundary is read before anyone files.

7. Under **Security problem**, read the line. It says to report privately, not as an issue, because an issue is public. ☐
8. Click **How to report a security problem**. ☐

   **You should see:** a scrollable box beginning "# Security", with sections including "Reporting a vulnerability" and "What we claim, and what we do not". Scroll to the end; nothing is cut off.

## Part E — offline

1. Close any open boxes. Disconnect the machine from the network: unplug the cable or turn off Wi-Fi. ☐
2. Reload the page (press F5, or the browser's reload button). Scroll back down to **About**. ☐

   **You should see:** the page loads normally. Askwell runs on this machine, so it needs no network to show its own settings.

3. Both addresses — the source and the issue address — are still shown as text. Click **Copy address** on each and paste: both paste correctly. ☐
4. Open the licence, the notices and the security policy one by one. The support text is already open. ☐

   **You should see:** each opens in full, exactly as in Parts B–D. None says "could not open".

5. Click **Open** next to the source address. ☐

   **You should see:** a new browser tab showing the browser's own "no internet" page. The Askwell tab is unchanged. Close the new tab.

6. Reconnect the network. ☐

## Part F — update checking

1. On an install where nobody has touched this control before, look under **Update checking**. ☐

   **You should see**, in this order:
   - "Askwell can check for updates once a week. That is one request for a static file, carrying your version number and nothing else. Off by default."
   - "Like any request on the internet, it also shows the server that holds the file your network address."
   - A checkbox, **unticked**, labelled **Check for updates once a week**.
   - Under it: "Off. It has never been turned on, and Askwell makes no request."

   If the line instead says "Off. You turned it off, and Askwell makes no request.", someone has turned it on and off before on this install. That is fine; the box must still be unticked.

2. Scroll up to **Privacy and security → Network activity** and write down the **permitted** number. Scroll back down to **About**. ☐
3. Tick **Check for updates once a week**. ☐

   **You should see:** the line under it shows "Saving…" briefly, then "On. Askwell checks once a week." No error text in red.

4. Reload the page and scroll back to **About**. ☐

   **You should see:** the box is still ticked and the line still says "On. Askwell checks once a week."

5. Untick the box. ☐

   **You should see:** "Saving…" briefly, then "Off. You turned it off, and Askwell makes no request."

6. Reload the page. The box is still unticked and the line is unchanged. ☐
7. Scroll up to **Network activity** again. ☐

   **You should see:** the **permitted** number is the same as in step 2, or at most one higher. Ticking and unticking the box does not itself make a request; the only request it can allow is the weekly check, and that fires on Askwell's own schedule.

8. **Terminal check — the decisions log.** The screen does not list decisions-log records, so read them directly: ☐

   ```
   scripts/dev.sh psql
   ```

   then, at the `askwell=>` prompt:

   ```
   SELECT kind, occurred_at FROM audit_decisions WHERE kind LIKE 'update_check%' ORDER BY occurred_at DESC LIMIT 2;
   ```

   **You should see:** two rows, newest first: `update_check_disabled`, then `update_check_enabled`, both timestamped a minute or two ago. Type `\q` to leave.

## Part G — a bundled text that is missing (optional, about 3 minutes)

This checks that a missing notices file is named as a failure, not shown as a blank box that could pass for a short file.

1. **Terminal:** move the built notices file aside: ☐

   ```
   mv web/out/notices.md /tmp/notices.md.bak
   ```

2. In the browser, reload **Settings**, scroll to **About**, and click **Third-party notices and licences, including the bundled model weights**. ☐

   **You should see:** red text: "Askwell could not open the third-party notices (it answered 404). It is bundled with this build, so this means the build is missing a file. The same text is in the source repository." No empty box.

3. **Terminal:** put it back: ☐

   ```
   mv /tmp/notices.md.bak web/out/notices.md
   ```

4. Reload, reopen the notices. They show in full again. ☐

## Part H — in the desktop app (only if the desktop shell is available)

1. Launch the desktop app. If the welcome page appears, click **Skip setup**. Click **Settings** in the rail and scroll to **About**. ☐
2. Next to both addresses there is **no Open link** — the app opens nothing outside Askwell. **Copy address** is there and works. ☐
3. The licence, notices, support text and security policy all open in full inside the app. ☐

---

## Known gaps

Not built by this ticket. Do not report these as defects.

- **No "check for updates now" button.** The backend has a manual check; the screen does not offer it yet. Issue #693.
- **The About section does not show when the last check ran or whether a newer version exists.** Showing a found update is `M7-UPDATE-FE-162`. Update delivery itself is `M7-UPDATE-BE-161` and later tickets, out of scope here.
- **The ticket expected the update control to refuse being turned on, because the mechanism was undecided.** That no longer applies. The mechanism was decided and built (`docs/decisions.md`, 2026-09-21; `M7-UPDATE-BE-161`), so the control really turns the check on and off. If it refuses, that is a defect.
- **"Never enabled by an upgrade" cannot be walked by hand here.** It holds because the backend's default is "never asked" and the screen never writes an answer on load (`web/lib/about.ts`). A real upgrade path is tested with the installer tickets.
- **The notices are plain text, not formatted tables.** They are the file as written, shown whole, so nothing can be dropped in rendering.
- **The introduction at the top of Settings still says "The surface for them arrives in M7."** That text predates this milestone and belongs to the Settings page, not to About.
