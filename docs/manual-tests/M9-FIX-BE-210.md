# Manual test — M9-FIX-BE-210, the update check tells you only about released versions

**Ticket:** `M9-FIX-BE-210`, issue #699. Someone who agreed to update checks was told about
versions that had never been released. The check read the development copy of Askwell's version
number, which goes up every time any change is merged. It went from `0.7.1` to `0.7.57` without
a single release being published, so the line "Newer version …" in **Settings → About** could
point at a download that did not exist.

Now the check reads a separate copy of the version number that is written only when a release
is actually published (`docs/release-procedure.md` §6a). No release has been published yet, so
that copy does not exist, and the check must treat that as "nothing newer" — not as a failure.
A version Askwell remembered from the old, wrong source is forgotten at the next check.

**Version under test:** `0.7.58`. Run `cat VERSION` and update this line if the version has
moved on.

**Time:** about 20 minutes.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by
clicking, starting from Askwell's front page. The terminal is used to start Askwell and, in
clearly marked **Terminal** steps, to put Askwell into a state the screen cannot produce on
demand: "an earlier check remembered a version that was never released".

**What is being checked.**

| Piece | File |
| ----- | ---- |
| Where the check reads from | `update_feed_url` in `api/src/askwell/config.py` |
| "The file does not exist" means "nothing published", not "could not reach" | `_fetch` in `api/src/askwell/update_check.py` |
| A remembered version is forgotten when nothing is published | `run_check` in the same file; `delete_setting` in `api/src/askwell/settings_store.py` |
| The words shown after **Check now** | `checkNowOutcome` in `web/lib/about.ts` |

The automated proof is in `api/tests/test_update_check.py`: `test_the_feed_is_the_releases_branch_not_main`,
`test_the_check_reads_the_published_feed_and_nothing_else`,
`test_no_release_published_shows_nothing_and_is_not_an_error`,
`test_no_release_published_forgets_a_version_the_old_feed_advertised` and
`test_a_server_error_is_still_unreachable_and_keeps_what_was_known`.

> **Parts B, C and D each make one real request to GitHub** (`raw.githubusercontent.com`), when
> you press **Check now**. It fetches one small file and carries your version number and nothing
> else. Nothing about your files is sent.

---

## Before you start

1. **Terminal:** see what the two version files on GitHub say right now. ☐

   ```
   curl -s -o /dev/null -w "releases: %{http_code}\n" https://raw.githubusercontent.com/Rumeasiyan/askwell/releases/VERSION
   printf "main: "; curl -s https://raw.githubusercontent.com/Rumeasiyan/askwell/main/VERSION
   ```

   **You should see:** `releases: 404` — the published copy does not exist, because nothing has
   been released yet — and a line such as `main: 0.7.57`, the development copy.

   If the first line prints `releases: 200` instead, a release has been published since this
   was written. Run `curl -s https://raw.githubusercontent.com/Rumeasiyan/askwell/releases/VERSION`
   and note the number: in the parts below, "This is the newest version." is only the right
   outcome if that number is no higher than the version under test.

2. **Terminal:** build both halves and start the stack. ☐

   ```
   cd ~/external/quantum-plus/askwell
   scripts/dev.sh build-api
   scripts/dev.sh web-build
   podman compose up -d --force-recreate api worker
   ```

   **You should see:** both builds finish with no red error text, and Compose reports `api` and
   `worker` as started. `--force-recreate` matters: a container that was already running keeps
   the old code, which still reads the development copy.

3. **Terminal:** confirm the running Askwell is the version under test. Wait about 20 seconds
   after step 2 first. ☐

   ```
   cat VERSION
   podman compose exec api cat /var/lib/askwell/running_version
   ```

   **You should see:** the same number twice, `0.7.58`. If the second is older, the container
   is still the old build; repeat step 2.

4. **Terminal:** clear any earlier update-check results, so the test starts from "never
   checked". This leaves your on/off answer alone. ☐

   ```
   scripts/dev.sh psql -c "DELETE FROM settings WHERE key LIKE 'update_check_%' AND key <> 'update_check_answer';"
   ```

   **You should see:** `DELETE` followed by a number (`0` is fine).

---

## Part A — reach Update checking the way a user would

1. Open a **private or fresh-profile** browser window and go to `http://127.0.0.1:8000`. This
   is the only address you type in this test. ☐

   **You should see:** either the **Ask** screen with a column of links down the left side, or,
   on an install that has never added a source, a page headed **Welcome to Askwell**.

2. If you see **Welcome to Askwell**, click **Skip setup** at its top right. ☐

   **You should see:** the **Ask** screen. The left column lists **Ask**, **Library**,
   **Clarifications**, **Memory** and **Settings**. Nothing there mentions an update.

3. Click **Settings** in the left column, then scroll down to the last section, **About**. ☐

   **You should see:** **Version** `0.7.58`, then **Licence**, **Source**, **Notices**. There is
   **no** "Newer version" line between **Version** and **Licence**.

4. Keep scrolling to **Update checking**. ☐

   **You should see:** the sentence "Askwell can check for updates once a week. That is one
   request for a static file, carrying your version number and nothing else. Off by default.",
   a checkbox **Check for updates once a week**, and a **Check now** button.

   If the checkbox is ticked, untick it and wait until the line under it reads "Off. You turned
   it off, and Askwell makes no request." The rest of the test assumes it is off.

## Part B — nothing has been released: nothing shown, and no error

This is the ticket's cold-start walkthrough: the check points at a place with no newer release.
Today that place has no release at all, which is also the ticket's edge case.

5. Click **Check now**. ☐

   **You should see:** the button reads "Checking…" for a moment, then goes back to **Check now**,
   and under it the line **"This is the newest version."**

   **You should not see:** "Askwell could not reach the file, so it does not know whether a
   newer version exists. Try again later." Before this ticket, a missing file would have been
   reported this way. No red text anywhere on the page.

6. Scroll back up to **About** without reloading. ☐

   **You should see:** still no "Newer version" line under **Version** — even though the
   development copy you read in "Before you start" step 1 has a version number, and before this
   ticket that number was what the check compared against.

7. Check the checkbox. ☐

   **You should see:** still **unticked**. **Check now** makes one request; it does not turn
   weekly checking on.

8. **Terminal:** confirm the one request went to the same place as before this ticket. ☐

   ```
   podman logs --since 5m askwell-egress-proxy-1 2>&1 | grep egress_permitted
   ```

   **You should see:** one `egress_permitted` line for the **Check now** you just pressed,
   ending `destination=raw.githubusercontent.com:443 … service=askwell-api-1`. No other
   destination. The request goes to the same host as before; only the file it reads changed
   (C1).

## Part C — a version remembered from the old source is forgotten

An install that checked before this ticket may have remembered a version that was only ever on
the development copy. This part puts that leftover in place and shows the next check clears it.

9. **Terminal:** record that an earlier check found `0.8.0`, as the old source could have said. ☐

   ```
   scripts/dev.sh psql -c "
   INSERT INTO settings (key, value, updated_at) VALUES
     ('update_check_latest_known_version', '0.8.0', now()),
     ('update_check_latest_known_since', '2026-09-20T10:00:00+00:00', now())
   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();"
   ```

   **You should see:** `INSERT 0 2`.

10. In the browser, reload the page (F5) and scroll to **About**. ☐

    **You should see:** directly under **Version**, a line **Newer version** `0.8.0` ·
    **Found 20 September 2026** (the date follows your browser's language), with a **Dismiss
    until a newer one** button. This is the misleading line a person would have seen: no
    `0.8.0` has been released.

11. Scroll to **Update checking** and click **Check now**. ☐

    **You should see:** "Checking…", then **"This is the newest version."**

12. Scroll back up to **About**. ☐

    **You should see:** the **Newer version** `0.8.0` line is **gone**. **Version** is followed
    directly by **Licence**.

13. Reload the page, then close the browser window entirely, open a new private window at
    `http://127.0.0.1:8000`, skip setup if asked, click **Settings** and scroll to **About**. ☐

    **You should see:** still no **Newer version** line. Askwell forgot `0.8.0` itself; the page
    is not just hiding it.

## Part D — a real failure is still a failure, and keeps what it knew

Only "the file does not exist" means "nothing released". Not reaching GitHub at all says nothing
about releases, so a version already found must stay found.

14. **Terminal:** put the `0.8.0` leftover back, exactly as in step 9. ☐

    **You should see:** `INSERT 0 2`.

15. Disconnect this computer from the network: turn Wi-Fi off, or unplug the cable. ☐

16. In the browser, reload the page, scroll to **Update checking**, and click **Check now**. ☐

    **You should see:** after "Checking…" (it can take up to about 10 seconds), **"Askwell could
    not reach the file, so it does not know whether a newer version exists. Try again later."**
    Scroll up: the **Newer version** `0.8.0` line is **still there**. Nothing else on the page
    breaks.

17. Reconnect to the network. Wait until a web page loads in another tab. Click **Check now**
    again. ☐

    **You should see:** **"This is the newest version."**, and the **Newer version** line gone.

## Cleanup

**Terminal:** put the update-check results back to "never checked":

```
scripts/dev.sh psql -c "DELETE FROM settings WHERE key LIKE 'update_check_%' AND key <> 'update_check_answer';"
```

**You should see:** `DELETE` followed by a small number.

---

## Known gaps

Not built by this ticket, or deliberate. Do not report these as defects.

- **"A newer release is shown" cannot be walked yet.** It needs a published release newer than
  the version under test, and none exists: the `releases` branch that holds the published copy
  is created by the first release (`docs/release-procedure.md` §6a), not by this ticket. Pushing
  it is a release act. The "newer version found" path is unchanged from `M7-UPDATE-BE-161`/`162`
  and is covered by `test_a_successful_check_records_the_remote_version` and the
  `M7-UPDATE-FE-162` manual test, which fakes it the same way Part C does.
- **"However far the development copy has moved" cannot be shown on screen.** The development
  copy is only ahead of a running build between merges, and a build from this branch is always
  at least as new. "Before you start" step 1 shows the two files differ; Part B shows only the
  published one is read. The automated test
  `test_the_check_reads_the_published_feed_and_nothing_else` asserts the development copy is
  never requested.
- **A mistyped feed address would also read as "nothing published".** GitHub answers a missing
  file and a wrong address the same way. Accepted in `docs/decisions.md` (2026-09-28): it fails
  towards "no update", never towards a download that does not exist, and the release checklist
  (G1) and procedure (§6a) both read the real address back.
- **The feed address cannot be changed from `.env`.** `.env.example` lists
  `ASKWELL_UPDATE_FEED_URL`, but `compose.yaml` does not pass it to Askwell, so setting it does
  nothing (#800). This test therefore uses the built-in address only.
- **Skipping release step §6a means nobody is told of that release.** That is a procedure step,
  not something the product can detect.
- **Messages are the same as before.** "This is the newest version." now also covers "nothing
  has been released at all". There is no separate wording for it, by design: to the person
  both mean there is nothing to download.
