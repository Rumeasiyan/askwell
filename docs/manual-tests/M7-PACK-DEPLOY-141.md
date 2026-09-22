# Manual test — M7-PACK-DEPLOY-141, the macOS installer

**Ticket:** `M7-PACK-DEPLOY-141` — a macOS installer covering the same ground as the Linux
(`M7-PACK-DEPLOY-139`) and Windows (`M7-PACK-DEPLOY-140`) ones, with macOS's own problems
named: Podman has no native runtime and needs its own VM ("the Podman machine"), that machine
only sees paths under the account's home directory by default, and Askwell ships unsigned.
**Version under test:** `0.7.9`
**Time:** logic runs in seconds on any Linux or macOS machine with bash; the runtime section
(`check_runtime`) was additionally run for real against this build host's own Podman (see Part
2) — everything past it needs the clean Mac this ticket's own Testing Notes ask for.

**Where this stops on purpose — same shape as `M7-PACK-DEPLOY-139`'s and `M7-PACK-DEPLOY-140`'s.**
This installer places what a release build produces; it does not build `Askwell.app` itself,
since that needs the Rust toolchain and a non-technical installing user must never be asked
for it. Producing that bundle, and a real offline bundle of container images and model
weights, remains issue #559 (open, and now names all three platforms) and
`M7-OFFLINE-DEPLOY-144` — nothing about this ticket closes either gap, it only refuses cleanly
in their absence.

**Signing is not this ticket's to close, and the ticket text is stale about it.** The ticket's
own Context/Background and Assumptions describe `M7-TAURI-DEPLOY-184` as delivering "signed
and notarised artefacts" to be "wired in" here, and its Assumptions section names an
unavailable certificate as "a blocking issue to raise rather than a workaround to ship." That
premise no longer matches the repository: `docs/decisions.md` (2026-08-26, "No trademark,
unsigned distribution, and Apache-2.0 stays") already settled this — Askwell ships **unsigned**
with published checksums and written bypass instructions (`docs/installing.md`), and real
signing survives only as `M7-TAURI-DEPLOY-184a`, explicitly deferred and blocked on the cost of
an Apple Developer enrolment, not on engineering. `deploy/windows/lib.ps1` already treats this
as settled fact (`Get-AskwellQuarantineMessage`: "Askwell's ... unsigned desktop shell"). This
is exactly the situation raised, not a workaround shipped silently: `install.sh` never checks
or claims a signature, and the acceptance criterion "the native binary runs without the user
disabling security features" is met only for the case this script actually handles — a
locally-built bundle copied by this installer on the same machine, which carries no
Gatekeeper quarantine attribute and is not expected to trigger the refusal `docs/installing.md`
documents for a *downloaded* release artefact. A downloaded, quarantined release still needs
the System Settings bypass `docs/installing.md` already walks through; this installer's
`launch()` step names that path if `codesign` reports no signature, rather than asserting the
criterion is met when it provably is not.

---

## Part 1 — the logic, no Mac required

```
bash deploy/macos/install.test.sh
```

**Expect:** every check passes — version comparison and Podman version parsing (identical
rules to the other two platforms), Podman-machine detection against `podman machine list`'s
table output (a machine present vs. absent, running vs. stopped), disk-space formatting,
`macOS`-specific path defaults (`~/Library/Application Support/Askwell`,
`~/Applications/Askwell.app`), install-record round-tripping, the same secrets checks the
other two suites run (`random_hex` distinctness and length; `generate_env_passwords` leaves no
`change-me` placeholder, keeps the sandbox-owner and sandbox-readonly credential pairs equal,
and leaves an unrelated line untouched), and the generated LaunchAgent `.plist` and quarantine
message.

Run on this Linux build host (no Mac available), confirmed 36/36 passing.

## Part 2 — `check_runtime` against a real Podman

Unlike `lib.ps1`'s Windows-only COM/registry calls, `lib.sh`'s Podman-machine functions
(`has_podman_machine`, `podman_machine_running`) only shell out to `podman`, which exists on
this Linux build host too (Podman supports a VM-backed "machine" on Linux as well as macOS,
even though Linux's own installer never uses one). Running `install.sh` for real up through
`check_runtime` was possible without a Mac:

```
podman machine init && podman machine start
```

**Observed:** `podman machine init` downloaded a VM image and created a machine; `podman
machine start` then failed on this host with `could not find "gvproxy"` — a missing helper
binary specific to this build container, not a bug in the installer. What matters for this
ticket: `install.sh` correctly detected the freshly-created machine (`has_podman_machine`
returned true), correctly reported it as not yet running (`podman_machine_running` returned
false before `start`), attempted `podman machine start`, and on that command's real failure
printed the named refusal (`"Could not start the Podman machine..."`) and exited non-zero
rather than continuing past a runtime it could not confirm. The machine was removed afterward
(`podman machine rm -f`) so this build host is left as it was found.

## Part 3 — the real cold-start walkthrough (blocked, same shape as Linux's and Windows')

This build host has no macOS machine and no macOS VM, so `install.sh`'s `place_files` (which
copies a real `.app` bundle and symlinks its executable), `register_session_start` (which
writes and loads a real `launchctl` LaunchAgent), and `launch` (which shells out to `open` and
`codesign`) cannot be exercised here the way Linux's own suite could stand in a fake shell
binary and run `install.sh` unmodified on the same checkout. Parts 1–2 above prove `lib.sh`'s
logic and the runtime-detection step against a real Podman; a real run needs the clean Mac this
ticket's own Testing Notes ask for:

1. On a clean Mac with no Podman and no Homebrew-installed Podman, run `install.sh`. **Expect:**
   if Homebrew itself is missing, a refusal naming `brew.sh` and that this script will not run
   Homebrew's own installer on the user's behalf; otherwise, a prompt to run
   `brew install podman`, then automatic creation and start of a Podman machine.
2. With Podman installed and a stand-in `Askwell.app` at
   `web/src-tauri/target/release/bundle/macos/Askwell.app` (a minimal bundle — an `Info.plist`
   and a trivial executable at `Contents/MacOS/askwell-shell` — real Tauri bundling needs the
   Rust toolchain this installer deliberately never invokes, same reasoning as the other two
   platforms' Part 2/3), run `install.sh` again. **Expect:** the bundle placed at
   `~/Applications/Askwell.app`, stack files under
   `~/Library/Application Support/Askwell/app`, `.env` written with generated passwords and no
   `change-me` value, a `~/Library/LaunchAgents/com.askwell.app.plist` written and loaded, an
   install record (`install.json`) written with the current `VERSION`, and `open` launching the
   app.
3. Log out and back in, confirm Askwell starts (the LaunchAgent's `RunAtLoad`).
4. Nominate a folder under `$HOME` (e.g. `~/Documents/cases`), add a PDF, ask a question, and
   click a citation to confirm the source viewer opens the file — proving the identity-mounted
   `ASKWELL_ROOTS_MOUNT` window, not new code this ticket added.
5. Nominate a folder on an external volume (outside `$HOME`) and confirm it registers and
   reports `not_mounted` rather than being silently unreadable, matching the message
   `check_roots_mount` prints at install time.
6. Quarantine the stand-in `Askwell.app` (or simulate by deleting it immediately after
   `place_files` copies it, before the post-copy existence check runs) and confirm the refusal
   names the app and XProtect/Console.app as the likely cause.
7. Download (not locally build) a real, unsigned release artefact through a browser so it
   carries the quarantine attribute, and confirm the System Settings → Privacy & Security →
   "Open Anyway" flow `docs/installing.md` documents is what actually clears it — this is the
   scenario the ticket's "expect the unidentified-developer warning" note describes, and it is
   **not** the same scenario as step 2 above (a same-machine build has no quarantine attribute
   at all).
8. Run `uninstall.sh`, confirm the LaunchAgent, CLI symlink and app bundle are gone and the
   data directory is untouched; then `--purge-data` and confirm it prompts and, on
   confirmation, removes it.

None of steps 1–8 have been run — issue **#592** tracks this the same way #590 tracks
Windows' equivalent gap, filed so the walkthrough is not silently assumed complete.

## A small, verified, unrelated gap found while implementing this ticket

This ticket's own "folder access permission requests ... explained" scope line overlaps with
`M7-TAURI-FE-182`'s stated acceptance criterion, so it was checked against the tree rather than
trusted from either ticket's closing comment. **The application-level explanation is genuinely
present and working**, contrary to an initial, overstated read during this session:
`web/components/settings/folders.tsx` calls `isMacOS()` and renders Askwell's own line beside
the native-picker button, and `docs/ux/add-source.md` §7 has the matching "macOS only" copy —
both real, both in `M7-TAURI-FE-182`'s actual merge commit (`f0ea93ae`), confirmed by reading
the files directly. What is still missing, narrower than first thought: `web/src-tauri/Info.plist`
and `tauri.conf.json`'s `bundle.macOS.infoPlist` key, which would carry
`NSDesktopFolderUsageDescription`/etc. so macOS's *own* system permission dialog shows
Askwell-authored wording rather than generic OS text — a refinement to the system prompt's own
copy, not the "an explanation appears" behaviour, which already ships. Filed as issue #593
(corrected in its own comment thread) rather than authored here, since Info.plist strings are
bundle-authoring work `M7-TAURI-FE-182` already claims as its scope; `install.sh` places
whatever bundle exists and does not author its permission-prompt content.

## Known gaps

- **No real cold-start walkthrough** (Part 3, above) — no Mac or Mac VM on this build host.
  Issue #592.
- **No CI job builds `Askwell.app`** — the same gap issue #559 already tracks for Linux and
  Windows; it blocks macOS identically and this ticket does not close it.
- **`Info.plist` usage-description strings for macOS's own system permission dialog do not
  exist** — the application-level explanation beside the picker button does exist and works
  (`folders.tsx`, `docs/ux/add-source.md` §7, from `M7-TAURI-FE-182`); only the OS-native
  prompt's own wording is still generic. Issue #593, not this ticket's to fix.
- **Podman-machine volume-mount detection is informational, not verified.** `check_roots_mount`
  states the default-mounts-home behaviour as a documented Podman fact rather than programmatic
  inspection of the running machine's actual mounts (`podman machine inspect`'s JSON field
  names were not available to verify against a running instance on this build host, and
  guessing them risks exactly the unverified-API mistake `AGENTS.md` §4 warns against). If a
  future Podman release changes the default, this message goes stale silently.
