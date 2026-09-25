# Manual test — M8-FIX-DOC-179, Askwell relicensed to GPLv3

**Ticket:** `M8-FIX-DOC-179`, closing #619. Askwell is now licensed under **GPL-3.0-or-later**, not Apache-2.0. Two things change. The first is what Askwell *says* about its own licence: the licence file, the About screen, the README, the product description and the package metadata. The second is the rule the release licence check applies to everything Askwell ships. That check used to refuse every GPL. Now it asks whether each component is *compatible with GPLv3*. It accepts `phonemizer` (GPLv3+, which spoken answers need), and it still refuses GPL-2.0-only, AGPL, SSPL, non-commercial, no-derivatives and unlicensed components. A licence it cannot place either way, such as a bare "GPL", stops the release until a person decides.

**Version under test:** `0.7.47`. Run `cat VERSION` and update this line if the version has moved on.

**Time:** about 20 minutes, most of it waiting for builds.

**Who can run it:** anyone with a browser and a terminal. Parts A and C use the terminal because the licence check is a command run before a release, and it has no screen. Every Askwell screen in Part B is reached by clicking, starting from Askwell's front page.

**What is being checked.**

- **The screen:** `web/components/settings/about.tsx`. The licence text it shows is the repository's `LICENSE`, and the notices text is `NOTICES.md`. Both are copied into the built interface at build time (`web/scripts/copy-support.mjs`, `web/scripts/copy-notices.mjs`).
- **The rule:** `DISALLOWED_LICENSES` and `UNCLEAR_LICENSES` in `api/src/askwell/notices.py`.
- **The check:** `scripts/generate_notices.py`, which `scripts/dev.sh notices` runs.
- **Why the licence changed:** `docs/decisions.md`, 2026-09-25, "Askwell is relicensed to GPLv3, so that spoken answers ship".

> **This test does not change any setting, send anything or turn anything on.** Part C writes a throwaway file under `.notices/`, which git ignores. It also briefly overwrites `NOTICES.md`, and Part C puts it back. Nothing leaves the machine. The licence check runs with no network.

---

## Before you start

Build the interface and start the stack:

```
cd ~/external/quantum-plus/askwell
scripts/dev.sh web-build
podman compose up -d --force-recreate api
```

**You should see:** the build finishes with no red error text. Compose reports the containers as started.

Don't skip `--force-recreate`. The build replaces `web/out`, and an API container that is already running keeps the old, now-empty copy. If you skip it, Askwell's front page says **"The interface has not been built"**, even though you just built it. If you see that page, run the `podman compose` line again.

Note the repository's version:

```
cat VERSION
```

**You should see:** one line, for example `0.7.47`. Write it down.

---

## Part A — the release licence check passes, with `phonemizer` accepted

This is the check a release has to pass (`docs/release-procedure.md` §3b). Before this ticket it failed on `phonemizer`.

1. In the terminal, run: ☐

   ```
   scripts/dev.sh notices
   ```

   **You should see:** it takes a minute or two, then ends with these four lines. The first two start with a blue `==>`:

   ```
   ==> web dependency licences
   ==> regenerating NOTICES.md and checking for a disallowed licence
   wrote /app/NOTICES.md
   no disallowed or unclear licences found
   ```

   There is no block headed `DISALLOWED OR UNCLEAR LICENCES FOUND — release gate fails:`.

2. Confirm the check ran cleanly: ☐

   ```
   echo $?
   ```

   **You should see:** `0`. Any other number means the check failed. Scroll up and read what it named.

3. Confirm `phonemizer` is listed in the notices, with its real licence: ☐

   ```
   grep phonemizer NOTICES.md
   ```

   **You should see:** exactly one line, `| phonemizer | 3.4.0 | GPL-3.0-or-later |`. A different version number is fine if dependencies have moved on. The licence must say `GPL-3.0-or-later`.

4. Confirm the check did not change the committed notices: ☐

   ```
   git status --short NOTICES.md
   ```

   **You should see:** no output. If you see ` M NOTICES.md`, the committed file is out of date with what is installed. That is a defect in whichever change last touched dependencies, so note it.

5. Confirm `phonemizer` is not given a pass by name. The rule should decide, not a list of package names: ☐

   ```
   grep -n -i phonemizer api/src/askwell/notices.py scripts/generate_notices.py
   ```

   **You should see:** mentions only inside comments or explanatory text (lines describing *why*). The name must not appear inside `DISALLOWED_LICENSES`, `UNCLEAR_LICENSES` or any exception list. If you see something like `ALLOWED = {"phonemizer"}` or `if name == "phonemizer"`, that is a defect: the ticket forbids it.

## Part B — Settings → About says GPLv3, reached the way a user would

1. Open a **private or fresh-profile** browser window, so no earlier session carries over. Open `http://127.0.0.1:8000`. This is where a user starts. ☐

   **You should see:** one of two screens. On an install that has been set up, it is the **Ask** screen, with a rail of links down the left side. On an install that has never been set up, it is a page headed **Welcome to Askwell**, with "A personal AI over your own files, on this machine." under it.

2. If you see **Welcome to Askwell**, click **Skip setup** at its top right. ☐

   **You should see:** the **Ask** screen. The left rail shows **Ask**, **Library**, **Clarifications**, **Memory** and **Settings**.

3. Click **Settings** in the left rail. ☐

   **You should see:** a page headed **Settings**, and **Settings** highlighted in the rail.

4. Scroll down past **Model and speed**, **Online AI**, **Folders Askwell may read**, **Storage**, **Privacy and security** and **Your data**. The last section is headed **About**. ☐

   **You should see:** under **About**: **Version**, then **Licence**, **Source** and **Notices**.

5. Read the **Version** line. ☐

   **You should see:** exactly the number `cat VERSION` printed.

6. Read the **Licence** line. ☐

   **You should see:** `GPLv3 (GPL-3.0-or-later)`. The word "Apache" appears nowhere in this line.

7. Click **Read the licence in full**. ☐

   **You should see:** a box opens below the link. It briefly shows "Reading…", then the text. The first two lines are "GNU GENERAL PUBLIC LICENSE" and "Version 3, 29 June 2007".

8. Scroll inside that box to the very bottom. ☐

   **You should see:** the last section is headed "How to Apply These Terms to Your New Programs". The last words are "<https://www.gnu.org/licenses/why-not-lgpl.html>." Nothing is cut off mid-sentence, and the page around the box does not scroll away while you scroll inside it. There is **no** copyright line naming a person, which is a known gap (#756), so do not report it.

9. Click **Read the licence in full** again. ☐

   **You should see:** the box closes.

10. Next to **Notices**, click **Third-party notices and licences, including the bundled model weights**. ☐

    **You should see:** a scrollable box. Its first heading is "Third-party notices", followed by **Bundled model weights**. The paragraph under that heading says C9 requires every model "to be GPLv3-compatible, to permit redistribution and commercial use, and to be ungated".

11. In the **Bundled model weights** table, find the row for the voice that speaks answers. ☐

    **You should see:** a row with `Synthesis | Kokoro-82M`, licence `Apache-2.0`. Every model row's licence is either Apache-2.0 or MIT. Those are the *models'* licences, not Askwell's, so Apache-2.0 is correct here.

12. Scroll down inside the box into **Python dependencies**. Use the browser's find (Ctrl+F, or Cmd+F on a Mac) and type `phonemizer`. ☐

    **You should see:** the line `| phonemizer | 3.4.0 | GPL-3.0-or-later |`. The same box also lists `kokoro-onnx` (MIT) and `espeakng-loader` (MIT). The text appears exactly as it is written in the file, so tables show as lines with `|` characters, not as formatted tables. That is expected.

13. Close the box. Disconnect the machine from the network by unplugging the cable or turning off Wi-Fi. Reload the page (F5), scroll back to **About**, and open **Read the licence in full** again. ☐

    **You should see:** the same GPLv3 text, in full. The licence is part of the installed interface, so it needs no network.

14. Reconnect the network. ☐

## Part C — the check still refuses what GPLv3 cannot carry

The ticket's rule is that the check still fails on a GPL-2.0-only or AGPL component, and that a versionless "GPL" is flagged, not waved through. This part checks that by giving the real check a made-up list of JavaScript packages. No package is installed.

1. Create the made-up list. Copy this whole block into the terminal as one paste: ☐

   ```
   cat > .notices/fake-licenses.json <<'EOF'
   {
     "GPL-2.0-only": [{"name": "fake-gpl2-only", "versions": ["1.0.0"]}],
     "AGPL-3.0-or-later": [{"name": "fake-agpl", "versions": ["1.0.0"]}],
     "GPL": [{"name": "fake-bare-gpl", "versions": ["1.0.0"]}],
     "GPL-3.0-or-later": [{"name": "fake-gpl3", "versions": ["1.0.0"]}]
   }
   EOF
   ```

   **You should see:** the prompt returns with no message.

2. Run the real check against it: ☐

   ```
   scripts/dev.sh run python /app/scripts/generate_notices.py /app/.notices/fake-licenses.json; echo "exit $?"
   ```

   **You should see:** exactly this, in this order:

   ```
   wrote /app/NOTICES.md

   DISALLOWED OR UNCLEAR LICENCES FOUND — release gate fails:
     - python/js package 'fake-agpl' 1.0.0: disallowed licence AGPL-3.0-OR-LATER
     - python/js package 'fake-bare-gpl' 1.0.0: unclear licence GPL, needs a decision
     - python/js package 'fake-gpl2-only' 1.0.0: disallowed licence GPL-2.0-ONLY
   exit 1
   ```

   Check three things:
   - **`fake-gpl3` is not named.** A GPLv3 package passes.
   - **`fake-bare-gpl` says "unclear … needs a decision"**, not "disallowed". The check does not know which way it goes, and it stops instead of guessing.
   - **The last line is `exit 1`.** A failed check must stop a release.

3. Put things back. Delete the made-up list and run the real check again, which restores `NOTICES.md`: ☐

   ```
   rm .notices/fake-licenses.json
   scripts/dev.sh notices
   git status --short NOTICES.md
   ```

   **You should see:** the same ending as Part A step 1 (`no disallowed or unclear licences found`), and then **no output** from `git status`. If `git status` shows ` M NOTICES.md`, the restore did not work. Run `git checkout NOTICES.md` and note it.

4. Run the check's own tests. These cover two cases this walkthrough cannot reach by hand: a bundled model with a **non-commercial** licence is still refused, and a Python package that says only "GPL" (with no version) is read as unclear. ☐

   ```
   scripts/dev.sh test tests/test_notices.py -v
   ```

   **You should see:** 23 tests, all `PASSED`. They include `test_gate_still_refuses_a_non_commercial_model`, `test_gate_still_fails_on_a_gpl_2_only_dependency`, `test_gate_still_fails_on_an_agpl_dependency`, `test_gate_fails_on_a_versionless_gpl_dependency` and `test_bare_gpl_classifier_alone_reads_as_unclear`. The last line reads `23 passed`.

## Part D — every place Askwell states its own licence says GPLv3

1. Check the licence file and the three package descriptions: ☐

   ```
   head -2 LICENSE
   grep -n '^license' api/pyproject.toml web/src-tauri/Cargo.toml
   grep -n '"license"' web/package.json
   ```

   **You should see:**
   - `LICENSE` begins "GNU GENERAL PUBLIC LICENSE" / "Version 3, 29 June 2007".
   - `api/pyproject.toml` and `web/src-tauri/Cargo.toml` each show `license = "GPL-3.0-or-later"`.
   - `web/package.json` shows `"license": "GPL-3.0-or-later",`.

2. Check the documents people read: ☐

   ```
   grep -n -i 'GPLv3\|GPL-3.0' README.md docs/PRD.md SUPPORT.md llms.txt
   ```

   **You should see:** at least one line from each of the four files. `README.md` is under its **Licence** heading. `docs/PRD.md` is in §7, "Askwell is open source under GPLv3". `SUPPORT.md` says "This is a free, GPLv3 project".

3. Check that none of them still claims Apache-2.0 for Askwell itself: ☐

   ```
   grep -n -i 'apache' README.md docs/PRD.md SUPPORT.md llms.txt
   ```

   **You should see:** no output. If any line says Askwell *is* Apache-2.0, that is a defect. A line naming Apache-2.0 as the licence of a *model* or a *dependency* would be correct, but none of these four files contains one today.

4. Open `AGENTS.md` and find constraint **C9** in the §3 table. ☐

   **You should see:** C9 says everything bundled "must be GPLv3-compatible, must permit redistribution and commercial use, and must not be access-gated". Just above the table, a paragraph says C9 changed on 2026-09-25 and points to `docs/decisions.md` and `M8-FIX-DOC-179`.

---

## Result

| Part | Pass / Fail | Notes |
| ---- | ----------- | ----- |
| A — check passes, `phonemizer` accepted by rule | | |
| B — About says GPLv3, full text opens and works offline | | |
| C — GPL-2.0-only and AGPL refused, bare GPL unclear, tests pass | | |
| D — every self-statement says GPLv3 | | |

---

## Known gaps

These are known and deliberate. Do not report them as defects.

- **No copyright holder is named anywhere.** The old Apache-2.0 `LICENSE` ended with "Copyright 2026 Suseenthiran Arulraj Rumeasiyan". The GPLv3 text is the FSF's verbatim copy and has no such line, and the notice was not moved anywhere else. Tracked in #756.
- **A released bundle does not yet come with its source, and the installers do not show the licence.** GPLv3 §6 requires the Corresponding Source to go with a distributed binary, and the repository is still private. This needs an owner decision about when the repository goes public. Tracked in #754. It blocks a public release, not this ticket.
- **AGPL is still refused**, even though GPLv3 §13 could technically carry it. That is a choice, not an oversight: `docs/decisions.md`, 2026-09-25.
- **Tools used only during development are not checked.** A GPL-2.0-only linter or test library would not fail the check, because it is never shipped (`test_gate_ignores_dev_only_tooling`).
- **The check runs only before a release.** It is not part of `scripts/dev.sh check` or CI, so a new GPL-2.0-only dependency is caught at release time, not when it is added (`scripts/generate_notices.py`, module docstring).
- **Voice is not re-tested here.** The ticket changes no voice behaviour. Spoken answers are covered by `docs/manual-tests/M6-TTS-BE-130.md` and `M6-TTS-BE-131.md`.
- **The notices box shows raw text**, with tables as `|` lines. That was already true (`M7-SET-FE-149`).
- **This is not legal advice.** The compatibility judgements follow the FSF's published list. A lawyer should review the licence before a public release.
