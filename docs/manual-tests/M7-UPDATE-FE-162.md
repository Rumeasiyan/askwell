# Manual test — M7-UPDATE-FE-162, telling someone a newer version exists

**Ticket:** `M7-UPDATE-FE-162`. When Askwell knows a newer version exists, it says so quietly and once: one line in **Settings → About**, with the version and the date Askwell found it. No pop-up, no banner, nothing near an answer. Before the person leaves to upgrade, it says what happens to their data. Dismissing the line holds until a further version is found, across restarts.

**Version under test:** `0.7.34`. Run `cat VERSION` and update this line if the version has moved on.

**Time:** about 30 minutes.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by clicking, starting from Askwell's front page. The terminal is used to start and restart Askwell and, in clearly marked **Terminal** steps, to put Askwell into a state the screen cannot produce on demand — "a newer version has been found" — and to read the decisions log, which the screen does not list.

**Why the terminal is needed to fake a newer version.** Askwell learns of a newer version by reading the repository's `VERSION` file on GitHub. On the day this was written that file says `0.7.33`, which is *older* than the `0.7.34` under test, so a real check finds nothing newer. The **Terminal** steps write what a check would have written, directly into Askwell's `settings` table, using the same keys the check uses (`api/src/askwell/update_check.py`).

**What is being checked.**

| Piece | File |
| ----- | ---- |
| The line, the dismiss button, the data-safety statement, **Check now** | `web/components/settings/about.tsx` |
| Their wording and when the line shows | `web/lib/about.ts` (`updateMarker`, `UPGRADE_DATA_SAFETY`, `checkNowOutcome`) |
| The found date, the stored dismissal, the upgrade record | `api/src/askwell/update_check.py` (`LATEST_KNOWN_SINCE_KEY`, `dismiss`, `record_running_version`) |
| Where the "last started as" version is kept | `/var/lib/askwell/running_version` in the `api` container (`Settings.running_version_path`) |

> **Part H makes one real request to GitHub** (`raw.githubusercontent.com`), when you press **Check now**. It fetches one small file carrying your version number. Parts F and I write records to the decisions log. If that matters, run this on a test install.

---

## Before you start

Build both halves and start the stack:

```
cd ~/external/quantum-plus/askwell
scripts/dev.sh build-api
scripts/dev.sh web-build
podman compose up -d --force-recreate api worker
scripts/dev.sh db upgrade head
```

**You should see:** both builds finish with no red error text. Compose reports the containers as started. The migration ends without an error.

`--force-recreate` is needed after a build: a container that is already running keeps the old code and the old copy of the interface.

Check the running version:

```
cat VERSION
podman compose exec api cat /var/lib/askwell/running_version
```

**You should see:** the same number twice, for example `0.7.34`. The second file is written when Askwell starts. Write the number down.

**Terminal — clear any earlier update-check results**, so the test starts from "never checked". This removes only the results of earlier checks and any earlier dismissal. It leaves your on/off answer alone.

```
scripts/dev.sh psql -c "DELETE FROM settings WHERE key LIKE 'update_check_%' AND key <> 'update_check_answer';"
```

**You should see:** `DELETE 0` or `DELETE` followed by a small number.

---

## Part A — get to About the way a user would, with nothing found

1. Open a **private or fresh-profile** browser window, so no earlier session carries over. Open `http://127.0.0.1:8000`. ☐

   **You should see:** either the **Ask** screen with a rail of links down the left side, or — on an install that has never indexed a source — a page headed **Welcome to Askwell**.

2. If you see **Welcome to Askwell**, click **Skip setup** at its top right. ☐

   **You should see:** the **Ask** screen. The left rail shows **Ask**, **Library**, **Clarifications**, **Memory** and **Settings**. Nothing in the rail mentions an update, and there is no dot or number beside **Settings**.

3. Click **Settings** in the rail. Scroll to the last section, headed **About**. ☐

   **You should see:** **Version** with the number you wrote down, then **Licence**, **Source**, **Notices**. There is **no** "Newer version" line between **Version** and **Licence**.

4. Scroll down to **Update checking** under About. ☐

   **You should see:** the checkbox **Check for updates once a week**, **unticked**, and under it "Off. It has never been turned on, and Askwell makes no request." (or "Off. You turned it off, and Askwell makes no request."). Below that: "Checking now makes that same one request, once, even if weekly checking is off." and a **Check now** button.

   Nothing on the page says a check failed, is missing, or has never happened in a way that reads as a problem. Never having checked is not an error.

   If the box is **ticked**, untick it now and wait for "Off. You turned it off…". The rest of this test assumes it is off.

## Part B — a newer version is found

5. **Terminal:** record that Askwell found version `0.8.0` on 3 September 2026, as a check would have. ☐

   ```
   scripts/dev.sh psql -c "
   INSERT INTO settings (key, value, updated_at) VALUES
     ('update_check_latest_known_version', '0.8.0', now()),
     ('update_check_latest_known_since', '2026-09-03T10:00:00+00:00', now()),
     ('update_check_last_checked_at', now()::text, now()),
     ('update_check_last_result', 'ok', now())
   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();"
   ```

   **You should see:** `INSERT 0 4`.

6. In the browser, reload the page (F5). Scroll back down to **About**. ☐

   **You should see**, directly under **Version**, one new line:

   - **Newer version** `0.8.0` · **Found 3 September 2026**. The date follows your browser's language, so an American English browser shows "Found September 3, 2026". Either is correct. The word is **Found**, never "Released".
   - A **Dismiss until a newer one** button on the same line.
   - Below it, a closed link: **How to upgrade, and what happens to your data**.

   There is no pop-up, no coloured banner across the top of the page, and nothing moved or covered.

7. Scroll back to the top of Settings, then click through every other item in the rail: **Ask**, **Library**, **Clarifications**, **Memory**. ☐

   **You should see:** nothing about a newer version on any of them. No badge or dot on **Settings** in the rail. The About line is the only place it appears.

## Part C — the update never comes near an answer

8. Click **Ask** in the rail. Type `What is in my files?` and send it. ☐

   **You should see:** Askwell answers, or — if nothing has been added yet or no model is running — says it cannot answer and why. Either is fine for this test. What matters: nothing about `0.8.0`, a newer version, or upgrading appears above, beside, inside or under the answer, and no pop-up opens while you wait or afterwards.

9. Close the browser tab. Open a new one at `http://127.0.0.1:8000` (skip setup again if asked). ☐

   **You should see:** the **Ask** screen, with no pop-up about a new version on launch. Askwell never shows one on launch.

## Part D — what happens to your data, said before leaving

10. Click **Settings**, scroll to **About**, and click **How to upgrade, and what happens to your data**. ☐

    **You should see**, in this order, top to bottom:

    1. "Install the new version over this one; there is no need to uninstall first. The installer replaces Askwell's own program files and leaves your data where it is: your indexes, what Askwell remembers, and the audit log are all kept. Uninstalling with the option to delete data is the only thing that removes them."
    2. "The installer for each platform is on the releases page."
    3. The address `https://github.com/Rumeasiyan/askwell/releases` as plain text, with a **Copy address** button, and — in a browser, not in the desktop app — an **Open** link.

    The data statement comes **before** the address. That order is the point: it is read before the person leaves, not discovered afterwards.

11. Click **Copy address** and paste into any text field. ☐

    **You should see:** the button reads **Copied**, and the pasted text is exactly `https://github.com/Rumeasiyan/askwell/releases`.

12. Click **How to upgrade, and what happens to your data** again. ☐

    **You should see:** it closes. The **Newer version** line is still there.

## Part E — dismissing holds across a restart

13. Click **Dismiss until a newer one**. ☐

    **You should see:** the button reads "Dismissing…" for a moment, then the whole **Newer version** line disappears. **Version** is followed directly by **Licence** again. No red error text.

14. Reload the page and scroll to **About**. ☐

    **You should see:** still no **Newer version** line.

15. **Terminal:** restart Askwell. ☐

    ```
    podman compose restart api
    ```

    Wait about 20 seconds.

16. Close the browser window entirely. Open a new private window at `http://127.0.0.1:8000`, skip setup if asked, click **Settings**, scroll to **About**. ☐

    **You should see:** still no **Newer version** line. The dismissal was stored by Askwell, not by the browser, so a restart and a fresh browser do not bring it back.

## Part F — a further version brings it back, as one line

17. **Terminal:** record that Askwell has now found `0.9.0`, on 17 September 2026. The running version is now two versions behind (`0.8.0` and `0.9.0` both newer). ☐

    ```
    scripts/dev.sh psql -c "
    UPDATE settings SET value = '0.9.0', updated_at = now() WHERE key = 'update_check_latest_known_version';
    UPDATE settings SET value = '2026-09-17T10:00:00+00:00', updated_at = now() WHERE key = 'update_check_latest_known_since';"
    ```

    **You should see:** `UPDATE 1` twice.

18. Reload the page and scroll to **About**. ☐

    **You should see:** the line is back: **Newer version** `0.9.0` · **Found 17 September 2026**. Exactly **one** "Newer version" line. It names the newest, `0.9.0`. There is no second line for `0.8.0` and no mention of how many versions were missed.

## Part G — turning checking off does not hide a version already found

19. Under **Update checking**, tick **Check for updates once a week**. ☐

    **You should see:** "Saving…", then "On. Askwell checks once a week." The **Newer version** line above is unchanged.

20. Untick it straight away. ☐

    **You should see:** "Saving…", then "Off. You turned it off, and Askwell makes no request."

    Untick promptly. The last check was recorded as "just now" in step 5, so no weekly check is due; the box being on for a minute makes no request.

21. Reload the page and scroll to **About**. ☐

    **You should see:** the **Newer version** `0.9.0` line is **still there**. Turning checking off stops future requests; it does not pretend the version already found does not exist.

## Part H — a version with no recorded date, then Check now

22. **Terminal:** remove the found date, as on an install whose version was found by a build before `0.7.34`. ☐

    ```
    scripts/dev.sh psql -c "DELETE FROM settings WHERE key = 'update_check_latest_known_since';"
    ```

23. Reload and scroll to **About**. ☐

    **You should see:** **Newer version** `0.9.0` with **no** date after it — no "Found", no blank "·", no made-up date.

24. Under **Update checking**, click **Check now**. This is the one real request in this test. ☐

    **You should see:** the button reads "Checking…" for a moment. Then one of:

    - "This is the newest version." — the published file says something no newer than the version under test (on the day this was written it says `0.7.33`). The **Newer version** line **disappears**, because the real check replaced the fake `0.9.0` from step 17. That is correct.
    - "`<version>` is available. It is shown under the version above." — the published file really is newer. The **Newer version** line names that version, with today's date.
    - "Askwell could not reach the file, so it does not know whether a newer version exists. Try again later." — the machine is offline. The **Newer version** line is unchanged. Nothing else on the page breaks.

    The checkbox stays **unticked** whichever it is. Check now does not turn weekly checking on.

## Part I — an applied upgrade is a decisions record

This fakes "this machine last ran an older version", then restarts, as an installer upgrade would.

25. **Terminal:** tell Askwell it last started as `0.7.30`, restart, and wait about 20 seconds. ☐

    ```
    podman compose exec api sh -c 'echo 0.7.30 > /var/lib/askwell/running_version'
    podman compose restart api
    ```

26. **Terminal:** read the newest decisions record, and the version file. ☐

    ```
    scripts/dev.sh psql -c "SELECT kind, payload, occurred_at FROM audit_decisions ORDER BY occurred_at DESC LIMIT 1;"
    podman compose exec api cat /var/lib/askwell/running_version
    ```

    **You should see:** one row: kind `upgrade_applied`, payload `{"to": "0.7.34", "from": "0.7.30"}` (the order of `to` and `from` may differ), timestamped within the last minute. The file now reads the version under test, `0.7.34`.

27. **Terminal:** restart once more and repeat step 26's query. ☐

    **You should see:** the same `upgrade_applied` row as the newest record, with the same timestamp. A restart with no version change records nothing new.

28. In the browser, reload, click **Settings**, scroll to **Your data**, and click the **Verify the log** button. ☐

    **You should see:** "Decisions — chain intact" and "Interactions — chain intact". The upgrade record joined the chain like any other decision.

## Cleanup

**Terminal:** put the update-check results back to "never checked":

```
scripts/dev.sh psql -c "DELETE FROM settings WHERE key LIKE 'update_check_%' AND key <> 'update_check_answer';"
```

The decisions records from Parts G and I stay. The log is append-only, and that is correct.

---

## Known gaps

Not built by this ticket, or deliberate. Do not report these as defects.

- **The date is when Askwell found the version, not when it was released.** The feed is the repository's bare `VERSION` file, which carries no date (`docs/decisions.md`, 2026-09-24). The label says "Found" for that reason.
- **A version found before `0.7.34` shows no date** until the next version is found. A date is never invented.
- **Applying the upgrade is the platform installer's job.** This screen gives the releases address and says what happens to data. It does not download or install anything.
- **The data-safety statement is one sentence for every platform.** That holds because all three installers keep the data directory on upgrade; `web/lib/about.test.ts` fails if one stops.
- **The first upgrade *to* `0.7.34` records nothing.** An install coming from an earlier version has no "last started as" file yet, so its first start at `0.7.34` writes the file and no record. The first `upgrade_applied` appears at the next upgrade. Part I fakes that file to see the record now.
- **Moving to an older version** records `version_changed`, not `upgrade_applied`. Not walked here.
- **A refused dismissal** (the line stays and red text says it is still shown) cannot be produced by clicking. It is covered by the unit tests.
- **A real check against GitHub currently finds `0.7.33`.** That is older than this build until this change is merged and `main`'s `VERSION` moves, so Part H usually ends with "This is the newest version."
- **The About section is the last one in Settings**, so the line is found by scrolling. That is the "quiet" the ticket asked for, not a defect.
