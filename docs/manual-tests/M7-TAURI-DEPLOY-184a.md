# Manual test — M7-TAURI-DEPLOY-184a, code signing and Apple notarisation

**Ticket:** `M7-TAURI-DEPLOY-184a` — sign the desktop shell, the installer and the native
inference binary on each platform, submit the macOS build to Apple for notarisation and staple
the result, so a freshly downloaded Askwell opens with no security warning.
**Version on disk:** `0.7.26`
**Status: not implemented. Blocked on a purchase — issue #636.**

**Read this before running anything.** This ticket has not been built. There is no Apple
Developer enrolment and no Windows code-signing certificate. Nobody can get either during a build
session, because both are purchases in the owner's name and take days to weeks to arrive. The
ticket's own header says not to start it until the certificates exist, and #42 (closed
2026-08-26) settled that Askwell ships **unsigned** until then (`docs/decisions.md`, 2026-08-26,
"No trademark, unsigned distribution, and Apache-2.0 stays"). Reading the code on disk confirms
this:

- `web/src-tauri/tauri.conf.json` has no signing identity, no notarisation settings and no
  Windows certificate settings. `bundle.active` is `false`, so it produces no installer bundle
  at all (issue #559).
- `.env.example` and `.github/workflows/` have no signing variables (for example `APPLE_*` or
  `TAURI_SIGNING_*`) and no signing step.
- `docs/release-procedure.md` starts with "Signing is not part of this", and its section "What a
  release records" says a signing identity and certificate expiry get recorded there "when
  `M7-TAURI-DEPLOY-184a` lands".
- `docs/installing.md` still begins "**Askwell is not code-signed.**"
- No GitHub release exists. `README.md` → Installing says "Not yet — there is no release."

This document has three parts:

- **Part 1** can be run today. It confirms the ticket is still blocked, so nobody mistakes the
  missing signing for a regression.
- **Part 2** describes what an installing person sees today. Treat it as the expected
  behaviour, not a defect.
- **Part 3** is the cold-start walkthrough that proves this ticket is done. It is written in
  full now so the session that implements the ticket has the pass bar ready. **Part 3 cannot run
  today.** Do not mark it passed and do not simulate it.

---

## Part 1 — confirm the ticket is still blocked (runnable today)

1. Open `https://github.com/Rumeasiyan/askwell/issues/636` in a browser.
   **Expect:** the issue is **Open**, titled "M7-TAURI-DEPLOY-184a: code signing/notarisation
   blocked on purchases", and has the label `blocked:decision`. The latest comment says there is
   still no Apple Developer enrolment and no Windows certificate.
   If the issue is **closed**, stop: the certificates may exist now, so go to Part 3.

2. In a terminal at the repository root, run:

   ```
   scripts/build-runner.sh --list | grep 184a
   ```

   **Expect:** exactly `M7-TAURI-DEPLOY-184a     BLOCKED`.
   Run on 2026-09-24: this output was observed. The `**[BLOCKED]**` marker in the ticket heading
   (`docs/backlog/M7-someone-else-can-install-it.md`) stops the unattended build runner from
   picking up the ticket again. Before the marker was added, the runner scheduled it three times
   (see #636's comments). If the output says `ready`, the marker has been lost, and the runner
   will pick up the ticket and waste a session.

3. Open `https://github.com/Rumeasiyan/askwell/releases`.
   **Expect:** "There aren't any releases here". There is nothing to download, so Part 2 and
   Part 3 cannot use a real artefact yet.

4. Open `docs/installing.md`.
   **Expect:** the first line after the title reads "**Askwell is not code-signed.** Linux
   installs normally. macOS and Windows will warn you the first time…". The page must stay like
   this until Part 3 passes. If someone shortens it before signing actually ships, users lose
   the bypass instructions they still need.

---

## Part 2 — what an installing person sees today (expected, not a defect)

This is the unsigned path shipped by `M7-TAURI-DEPLOY-184`. Its full walkthroughs are in
`docs/manual-tests/M7-TAURI-DEPLOY-184.md` and the per-platform installer tests
(`M7-PACK-DEPLOY-139.md` Linux, `140.md` Windows, `141.md` macOS). In short, until this ticket
lands, a tester **should** see:

- **macOS:** the first launch is refused with "Askwell cannot be opened because the developer
  cannot be verified" (newer macOS versions say "Apple could not verify 'Askwell' is free of
  malware…"). Getting past it takes **System Settings → Privacy & Security → Open Anyway**.
- **Windows:** a blue SmartScreen panel, "Windows protected your PC", with **Don't run** as the
  default button. Getting past it takes **More info → Run anyway**.
- **Linux:** no warning.

Do not report any of these as defects while #636 is open. `docs/installing.md` documents them on
purpose, and puts the checksum check above the bypass instructions.

---

## Part 3 — the acceptance walkthrough, once signing lands (NOT runnable today)

**Run this only when all of the following are true.** If any is false, stop here. The ticket is
not done, and a partial run proves nothing.

- #636 is closed, with a closing comment that names the signing identity and its expiry date.
- #559 is closed. A real per-platform installer is published: an `.app` inside a `.dmg` on macOS
  and an `.msi` or `.exe` on Windows.
- #676 is resolved. Today the Windows installer is a PowerShell script that Windows' default
  settings refuse to run, signed or not. And Askwell does not ship `llama-server` itself, so
  there is no inference binary to sign.
- A GitHub release exists with the installers **and** a `SHA256SUMS` file.

**You need** three machines that have **never had Askwell installed**: a Mac, a Windows PC and a
Linux PC. Each must be on a normal user account with **default security settings** — do not
change Gatekeeper, SmartScreen, antivirus or PowerShell settings. A borrowed work Mac is the most
realistic test, because the ticket's own example scenario is "a work Mac with default security
settings". Use a fresh virtual machine only if no real machine is available, and say which you
used when you record the result.

Record what you see at **every** step. A warning that appears and is clicked past is a
**failure**, even if Askwell works afterwards.

### 3a. macOS

1. In Safari, open the Askwell release page on GitHub. Click the `.dmg` file for this version and
   click `SHA256SUMS`. Both go to your **Downloads** folder.
   **Expect:** both files appear in Downloads. Safari shows no warning about the download.
2. Check the checksum **before** opening anything. Open **Terminal** (Launchpad → search
   "Terminal") and type:

   ```
   cd ~/Downloads
   shasum -a 256 Askwell-<version>.dmg
   ```

   **Expect:** the long value printed exactly matches the line for that file in `SHA256SUMS`
   (open `SHA256SUMS` in TextEdit to compare). If it does not match, stop, do not open the file,
   and file an issue. Signing does not replace this step (see "What passing means"
   below).
3. In Finder, open **Downloads** and double-click the `.dmg`.
   **Expect:** a window opens showing the Askwell icon and an Applications folder. **Fail if**
   macOS says the disk image "cannot be opened", "is damaged", or "could not be verified".
4. Drag the Askwell icon onto the Applications folder, then eject the disk image (click the eject
   arrow next to it in the Finder sidebar).
   **Expect:** Askwell appears in **Applications**.
5. Open **Applications** and double-click **Askwell**.
   **Expect:** at most one standard macOS question: "'Askwell' is an app downloaded from the
   Internet. Are you sure you want to open it?", with an **Open** button. A notarised app still
   shows this once, and it is **not** a failure.
   **Fail if** you see any of these instead:
   - "Askwell cannot be opened because the developer cannot be verified"
   - "Apple could not verify 'Askwell' is free of malware"
   - "'Askwell' is damaged and can't be opened"
   - a dialog whose only buttons are **Done** or **Move to Trash**

   These mean the app was not signed or not notarised, or the notarisation ticket was not
   stapled.
6. Click **Open**.
   **Expect:** the Askwell window opens. It is Askwell's own window, not a browser tab. First-run
   starts and shows the hardware check and the model setup. **Fail if** you have to go to
   **System Settings → Privacy & Security** at any point.
7. Complete first-run by clicking through it, the way a new user would.
   **Expect:** Askwell says it is ready. No macOS dialog about "askwell-inference", "llama-server"
   or any other helper program appears while it starts. Such a dialog would mean the inference
   binary was left out of signing, which is the most common notarisation failure: a nested
   binary nobody signed.
8. Add one document: click **Add**, choose any PDF from your Mac, and wait for it to finish
   indexing. Then ask a question the document answers.
   **Expect:** an answer that cites the document by name and page. This is the first time
   inference actually runs, so if the inference binary were unsigned, macOS would block it at
   this step.
9. Quit Askwell (**Askwell → Quit**) and open it again from **Applications**.
   **Expect:** it opens straight away, with no question at all this time.

### 3b. Windows

1. In Edge (Windows' built-in browser), open the Askwell release page. Download the `.msi` or
   `.exe` for this version, and `SHA256SUMS`.
   **Expect:** both finish downloading. **Fail if** Edge shows "isn't commonly downloaded" or
   "could harm your device" and makes you pick **Keep**. See the note about reputation under
   Known gaps before deciding how to record this.
2. Check the checksum. Open **Start**, type **PowerShell**, open it, and type (using the real
   file name):

   ```
   cd $HOME\Downloads
   Get-FileHash .\Askwell-<version>.msi -Algorithm SHA256
   ```

   **Expect:** the long `Hash` value exactly matches the line for that file in `SHA256SUMS`
   (open `SHA256SUMS` in Notepad to compare). If it does not match, stop and file an issue.
3. Open **Downloads** in File Explorer and double-click the installer.
   **Expect:** Windows' standard "Do you want to allow this app to make changes to your device?"
   prompt, if one appears at all, shows **Verified publisher:** followed by the publisher's name.
   **Fail if** it says **Publisher: Unknown**, or if a blue "Windows protected your PC"
   SmartScreen panel appears.
4. Click **Yes** and follow the installer, keeping the default options.
   **Expect:** it finishes, and Askwell appears in the Start menu.
5. Open **Start**, find **Askwell**, and click it.
   **Expect:** the Askwell window opens and first-run starts. **Fail if** SmartScreen, Windows
   Security or a "this app has been blocked" notification appears.
6. Complete first-run, add one document, and ask a question it answers, as in macOS steps 7–8.
   **Expect:** an answer citing the document by name and page. No Windows Security or firewall
   dialog names a helper program.
7. Close Askwell, then open it again from the Start menu.
   **Expect:** it opens with no prompt.

### 3c. Linux

Linux has no warning today, so the point of this section is to confirm signing did not break
anything.

1. Download the Linux package for this version and `SHA256SUMS` from the release page.
2. Open a terminal in the download folder and run `sha256sum -c SHA256SUMS --ignore-missing`.
   **Expect:** the package's line ends in `OK`.
3. Install it the way `docs/installing.md` → Linux says, then open Askwell from the applications
   menu.
   **Expect:** Askwell opens and first-run starts, exactly as before this ticket.
4. Complete first-run, add a document, and ask a question it answers.
   **Expect:** an answer citing the document by name and page.

### 3d. The release side

Run these on the release machine after the platform runs pass:

1. Open the build log for the release.
   **Expect:** notarisation appears as its own step, with a start time, an end time and Apple's
   result ("Accepted"). It is a real wait, not a line that returns instantly. The release
   procedure (`docs/release-procedure.md`) must list it as a step with a duration.
2. Search the build log, the release artefacts and the repository for the certificate password,
   the Apple app-specific password and the certificate file name.
   **Expect:** no matches anywhere (C8, and the ticket's validation rule "credentials never reach
   a log, a commit, or a build artefact").
3. Open `docs/installing.md`.
   **Expect:** the "Why there is a warning", macOS bypass and Windows bypass sections are gone or
   reduced to the parts still true, such as Windows reputation on a new version. The checksum
   section is **still there, and still first**.

### What passing means

All of 3a–3d pass, on real clean machines, with no warning at any step other than the ones named
as allowed above. Checksums still match. Signing shows **who** published the file, and the
checksum shows the bytes were not changed on the way. Neither replaces the other, so a release
that drops `SHA256SUMS` because it is now signed fails this ticket.

---

## Known gaps

These are deliberately not built, or known limitations. Do not report them as defects.

- **The whole ticket is unbuilt**, blocked on buying an Apple Developer enrolment and a Windows
  code-signing certificate (#636). Until then, the Part 2 warnings are the intended behaviour.
- **Certificates alone will not be enough** — #676. Today's Windows installer is a PowerShell
  script, and Windows' default settings refuse to run scripts whether they are signed or not.
  The inference program Askwell starts (`llama-server`) is found on the user's machine, not
  shipped by Askwell, so there is nothing of Askwell's to sign there. `docs/installing.md`
  describes `.dmg`/`.exe`/`.rpm` files that no pipeline produces yet (#559). The recommendation
  in #676 is not to buy the Windows certificate until #559 produces a real `.msi`/`.exe`.
- **Windows reputation per version.** With a standard (non-EV) certificate, a new version can
  still trigger SmartScreen or Edge's "isn't commonly downloaded" warning until enough people
  have downloaded it. Signing reduces this but does not remove it. The ticket accepts it as a
  known gap, and an EV certificate avoids it at a higher price. If it appears in 3b, record it
  as "reputation warning, standard certificate" rather than as a signing failure — but only if
  3b step 3 showed **Verified publisher**. With **Publisher: Unknown**, it is a real failure.
- **Notarisation rejected and certificate expiry mid-release** are edge cases the ticket names.
  Nothing implements them yet, so there is nothing to test. When built, the release must stop
  rather than publish a half-signed artefact.
- **App store distribution and any runtime signature check** are out of scope by the ticket's
  own text. Askwell never checks its own signature at runtime, and signing adds no network call
  to the product. C1 and the cable-unplugged release test (`docs/offline-release-test.md`) are
  unaffected.
- **No clean macOS or Windows test hardware exists on the build host** (#590 Windows, #592
  macOS). Part 3 needs real machines, provided by a person.
