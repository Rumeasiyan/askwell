# Manual test — M7-PACK-DEPLOY-140, the Windows installer

**Ticket:** `M7-PACK-DEPLOY-140` — a Windows installer covering the same ground as the Linux
one (`M7-PACK-DEPLOY-139`), with Windows' own problems named: WSL2's virtualisation
requirement, antivirus quarantine of the native inference binary and the unsigned shell, the
`MAX_PATH` limit, and registered-root paths crossing the WSL2 virtualisation boundary.
**Version under test:** `0.7.8`
**Time:** about 25 minutes on a clean Windows VM with the release artefacts already built; the
logic itself (`deploy/windows/install.test.ps1`) runs in seconds on any machine with
PowerShell 7, no VM and no Windows required.

**Where this stops on purpose — same shape as `M7-PACK-DEPLOY-139`'s.** This installer places
what a release build produces; it does not build `askwell-shell.exe` itself, since that needs
the Rust toolchain and a non-technical installing user must never be asked for it. Producing
that binary, and a real offline bundle of container images and model weights, remains issue
#559 (still open) and `M7-OFFLINE-DEPLOY-144` — both apply to Windows exactly as they did to
Linux; nothing about this ticket closes that gap, it only refuses cleanly in its absence, the
same way `M7-PACK-DEPLOY-139` does. The shell also does not start the containers itself
(`M7-TAURI-DEPLOY-183`, not built) — a real launch still needs `podman compose up -d` run once
by hand until that lands.

**Registered-root path handling across the WSL2 boundary is not new code in this ticket.**
`api/src/askwell/roots.py`'s `probe()` already reports a folder that is not there — unplugged
drive, disconnected share, **or a Windows drive letter that changed between sessions** — as
`unavailable` with a "reconnect it, nothing needs re-indexing" message, and
`extract_common`'s per-file `OSError` handling already turns an unreadable file (including one
past Windows' `MAX_PATH`) into a named, per-file failure rather than a failed drop. Both were
written platform-agnostically in `M1-ADD-ING-021` and are exercised here, not rebuilt.

---

## Part 1 — the logic, no VM required

```
pwsh -File deploy/windows/install.test.ps1
```

(PowerShell 7 — `pwsh` — not Windows PowerShell 5.1. This suite was written and run against
PowerShell 7.4 on this build host; a Windows machine's `winget install -e --id
Microsoft.PowerShell` is what a real installing user would already have for `pwsh` to exist at
all, but the *installer itself* targets whatever PowerShell ships with Windows.)

**Expect:** every check passes — virtualisation detection against `systeminfo`'s own "Hyper-V
Requirements" text (firmware flag on, firmware flag off, and a hypervisor already running, which
counts as enabled since virtualisation is not merely available but in active use), the Windows
build-number floor WSL2 needs, version comparison, Podman version parsing, disk-space
formatting, the `MAX_PATH` check, path defaults under `LOCALAPPDATA`, install-record
round-tripping, and the same secrets checks `deploy/linux/install.test.sh` runs:
`New-AskwellRandomHex` produces distinct 64-character lowercase hex strings, and
`Set-AskwellEnvPasswords` leaves no `change-me` placeholder while keeping the sandbox-owner and
sandbox-readonly credential pairs equal to each other (the Windows side of issue #584's fix).

Run on this Linux build host, confirmed 33/33 passing.

## Part 2 — syntax and structure, no VM required

```
pwsh -NoProfile -Command '
  $errors = $null
  foreach ($f in "deploy/windows/install.ps1","deploy/windows/uninstall.ps1","deploy/windows/lib.ps1") {
    $tokens = $null
    [System.Management.Automation.Language.Parser]::ParseFile($f, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors.Count -gt 0) { $errors } else { "$f OK" }
  }
'
```

**Expect:** all three files parse with no errors. This is not a substitute for running
`install.ps1` for real — it only proves there is no syntax mistake blocking that run.

## Part 3 — the real cold-start walkthrough (blocked, same shape as Linux's)

This build host has no Windows machine and no Windows VM, so `install.ps1`'s `Test-AskwellRuntime`
(which shells out to `systeminfo` and, on a machine without Podman, `winget`), `Copy-AskwellFiles`
(which writes to Windows-style paths under `LOCALAPPDATA`), and `Register-AskwellShortcuts`
(which creates `.lnk` files via `WScript.Shell`, a Windows-only COM object) cannot be exercised
here the way `deploy/linux/install.test.sh` could stand in a fake shell binary and run the real
`install.sh` on this same Linux checkout. Parts 1–2 above prove `lib.ps1`'s logic and all three
scripts' syntax; a real run needs the clean Windows VM this ticket's own Testing Notes ask for:

1. On a clean Windows 10/11 VM with virtualisation **disabled** in the hypervisor's firmware
   settings, run `install.ps1`. **Expect:** refusal naming "Virtualisation is off", the
   BIOS/UEFI setting name(s) to look for, and that Askwell cannot enable it itself.
2. Enable virtualisation, reboot, run `install.ps1` again with a stand-in
   `web\src-tauri\target\release\askwell-shell.exe` (a one-line batch or PowerShell script
   renamed `.exe`, or a trivial compiled stub — real Rust build needs the toolchain this
   installer deliberately never invokes, same reasoning as Linux Part 2). **Expect:** Podman
   Desktop installed or detected, application files placed under
   `%LOCALAPPDATA%\Askwell\app`, `.env` written with generated passwords and no `change-me`
   value, a Start-menu entry and a Startup-folder shortcut created, an uninstall registry entry
   under `HKCU:\...\Uninstall\Askwell`, an install record (`install.json`) written with the
   current `VERSION`, and the shell launching.
3. Reboot and confirm Askwell starts (the Startup-folder shortcut).
4. Nominate a folder on a normal Windows path (e.g. `C:\Users\<name>\Documents\cases`), add a
   PDF, ask a question, and click a citation to confirm the source viewer opens the file —
   proving the WSL2-boundary bind mount, not new code this ticket added.
5. Quarantine `askwell-inference.exe`'s stand-in via Windows Defender (or simulate by deleting
   it immediately after `Copy-AskwellFiles` places it, before the post-copy `Test-Path` check
   runs) and confirm the refusal names the file and quarantine as the likely cause.
6. Change the VM's data drive's letter (detach and reattach at a different letter, or edit it
   in Disk Management) and confirm the registered root reports **unavailable** rather than
   every document inside it reporting missing.
7. Run `uninstall.ps1`, confirm the Start-menu entry, Startup shortcut and registry entry are
   gone and the data directory is untouched; then `-PurgeData` and confirm it prompts and, on
   confirmation, removes it.

None of steps 1–7 have been run — issue **#590** tracks this the same way #559 tracks Linux's
equivalent gap, filed so the walkthrough is not silently assumed complete.

## Known gaps

- **No real cold-start walkthrough** (Part 3, above) — no Windows machine or VM on this build
  host. Issue #590.
- **No CI job builds `askwell-shell.exe`** — the same gap issue #559 already tracks for Linux;
  it blocks Windows identically and this ticket does not close it.
- **Windows PowerShell 5.1 is untested.** `install.ps1`/`lib.ps1` avoid version-7-only syntax
  where noticed, but only PowerShell 7 (`pwsh`) ran here. Windows 10/11 ship 5.1 by default;
  `pwsh` is a separate install (`winget install -e --id Microsoft.PowerShell`), which this
  installer does not itself check for or bootstrap — a machine with only 5.1 would need to run
  it via `powershell.exe -File install.ps1` untested against 5.1's older parser and cmdlet set.
- **Unsigned artefact** — code-signing is `M7-TAURI-DEPLOY-184`, not built. Expect a Windows
  SmartScreen warning on first launch of the unsigned shell in addition to the antivirus
  quarantine risk this ticket names.
- **The shell does not start the containers itself** — `M7-TAURI-DEPLOY-183`, not this ticket's
  dependency, not built. `podman compose up -d` still needs to be run once by hand.
- **No update mechanism** — blocked, per the ticket's own Testing Notes.
- **Enterprise-managed machines** with restrictive Group Policy (blocked `winget`, disallowed
  WSL2, non-admin accounts with no path to elevation) may not install at all — named as a known
  gap in the ticket's own Testing Notes, not fixed here.
