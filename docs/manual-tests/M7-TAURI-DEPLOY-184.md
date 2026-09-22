# Manual test — M7-TAURI-DEPLOY-184, unsigned distribution with checksums

**Ticket:** `M7-TAURI-DEPLOY-184` — publish a `SHA256SUMS` file with every release, put
`docs/installing.md` above the artefact list on the release page, and document the release
procedure. No signing, no notarisation — that is `M7-TAURI-DEPLOY-184a`, deferred.
**Version under test:** `0.7.10`

**The ticket's own Acceptance Criteria text described a signed, notarised product** —
"signing credentials exist only as environment secrets", "notarisation rejected for a nested
binary". That directly contradicted the same ticket's Scope ("Code signing and Apple
notarisation — deferred to `184a`") and its own header note ("Signing is deferred, not
dropped"). This was already caught and fixed at the source, not worked around here:
`docs/backlog/M7-someone-else-can-install-it.md`'s AC/Scenarios/Dependencies/Testing Notes for
`184` were corrected in the same change that shipped this (`docs/decisions.md`, 2026-09-23,
"Release checksums and procedure ship; the ticket's own Acceptance Criteria described the wrong
(signed) product"). This test doc follows the corrected scope: checksums and unsigned
distribution, not signing.

**No release has been published yet.** `README.md`'s own Installing section says "Not yet —
there is no release." — confirmed by reading it directly. There is also no pipeline that
produces a real installable bundle per platform yet (issue #559, open — `tauri.conf.json` still
has `bundle.active: false`). So the true end-to-end cold-start walkthrough this ticket's
Testing Notes ask for — download a *real published* release, verify it, install it on a clean
machine — cannot happen yet, for the same reason `docs/manual-tests/M7-PACK-DEPLOY-140.md` and
`141.md` are blocked (issues #590, #592). What follows tests everything that exists today:
the checksum tool for real, and the documents word for word, on this build host.

---

## Part 1 — generate and verify checksums, for real

No app to launch for this ticket — it is a release-time script and three documents. Start from
a directory of release artefacts, the way a release actually would.

```
bash scripts/release-checksums.test.sh
```

**Expect:** `9 passed, 0 failed` — the happy path, deterministic ordering, refusal on an empty
or missing directory, and that `SHA256SUMS` never lists itself even across reruns.

Then run it by hand against stand-in artefacts, the way `docs/release-procedure.md` §3
instructs a release to:

```
D=$(mktemp -d)
printf 'fake linux tarball\n'   > "$D/askwell-0.7.10-linux.tar.gz"
printf 'fake windows zip\n'     > "$D/askwell-0.7.10-windows.zip"
printf 'fake macos tarball\n'   > "$D/askwell-0.7.10-macos.tar.gz"
scripts/release-checksums.sh "$D"
```

**Observed:** the script wrote `$D/SHA256SUMS` and printed all three lines to the terminal —
one hash per artefact, alphabetically sorted by filename, matching §3's claim that the printed
output is what a release should read before continuing.

Verify the upload the way `docs/release-procedure.md` §5 and `docs/installing.md`'s own
"Verify what you downloaded" section both instruct — from outside the build, against the
published file:

```
(cd "$D" && sha256sum -c SHA256SUMS)
```

**Observed:** all three lines reported `OK`.

Then prove a mismatch is actually caught, not just theoretically possible — append one byte to
an artefact after its checksum was generated, simulating a corrupted or tampered download, and
re-verify:

```
printf 'tampered\n' >> "$D/askwell-0.7.10-linux.tar.gz"
(cd "$D" && sha256sum -c SHA256SUMS)
```

**Observed:** `askwell-0.7.10-linux.tar.gz: FAILED`, the other two still `OK`, `sha256sum`
exits non-zero and prints `WARNING: 1 computed checksum did NOT match`. This is the exact
signal `docs/installing.md` tells a user to stop at ("If it does not match, stop. Do not run
it.").

## Part 2 — read `docs/installing.md` the way a downloading user would

No login, no app — this is the page a user reaches before ever running an installer. Read it
top to bottom as written, checking it against what actually exists on disk.

1. Open `docs/installing.md`. **Expect:** the first substantive section after the summary is
   "Verify what you downloaded — do this first", not the bypass instructions. Confirmed — the
   verify section appears before the Linux/macOS/Windows install sections in the file.
2. Confirm it gives a copy-pasteable command per platform: `shasum -a 256 <file>` for
   Linux/macOS, `Get-FileHash <file> -Algorithm SHA256` for Windows PowerShell. Both present.
3. Confirm the macOS section names the exact refusal text
   ("*Askwell cannot be opened because the developer cannot be verified.*") and the exact path
   through System Settings — **System Settings → Privacy & Security → Open Anyway** — rather
   than the outdated right-click-Open shortcut, and says explicitly that the right-click route
   "no longer works on recent macOS versions." Present.
4. Confirm the Windows section names SmartScreen's real default-button behaviour — **Don't
   run** is the default, **More info** is described as "the small link above the buttons, which
   is easy to miss" before **Run anyway** — matching how SmartScreen actually presents this
   choice. Present.
5. Confirm the closing "honest part" section states plainly that the bypass instructions teach
   users to click past a security warning, and that the checksum, not the bypass, is what
   protects them. Present, and it is the document's actual closing section.

## Part 3 — the release procedure and template, read against what they promise

1. Open `docs/release-procedure.md`. Step through §§1–6 as written. **Expect:** version
   confirmation, artefact assembly, checksum generation (Part 1 above), publish via
   `gh release create` with `--notes-file docs/release-notes-template.md`, verify-from-outside,
   then cold-start install verification per platform. Matches file contents read directly.
2. Confirm §2 names the real gap rather than implying a working pipeline: "No pipeline produces
   a real installable bundle per platform" and points at issue #559. Present.
3. Open `docs/release-notes-template.md`. **Expect:** the `docs/installing.md` link appears
   before the changelog placeholder, with the same "verify the checksum first" framing
   `docs/installing.md` itself uses. Present — the link and verify-first line are the first
   content in the file, the changelog placeholder comment is last.
4. Open `README.md`'s Installing section. **Expect:** it links `docs/installing.md` and states
   plainly that no release exists yet, rather than pointing at a release page that would 404.
   Present, and accurate — confirmed against the actual absence of any GitHub release for this
   repository.

## Part 4 — the real cold-start walkthrough (blocked, not simulated)

This is the part the ticket actually cares about most — a stranger's machine, a real download,
the real warning, the real checksum check against a real published `SHA256SUMS` — and it cannot
run today:

- There is no published release to download (`README.md`, confirmed above).
- No pipeline builds the real per-platform bundle yet (issue #559, open).
- Even once a release exists, the per-platform cold-start runs live in their own docs and their
  own gaps: `docs/manual-tests/M7-PACK-DEPLOY-139.md` (Linux, run), `140.md` (Windows, blocked
  on issue #590 — no test hardware), `141.md` (macOS, blocked on issue #592 — no test hardware).

None of the three platform walkthroughs' "download a real artefact, check `SHA256SUMS`, install
on a clean machine" step has happened for real yet. This ticket does not close that gap — it
only makes sure the checksum tool and the documents are correct and ready for the first release
that does exist.

## Known gaps

- **No real release exists**, so the download-and-verify flow this ticket is ultimately for has
  never run against a genuine published `SHA256SUMS` and a genuine downloaded artefact — only
  against stand-in files on this build host (Part 1). Not a defect in this ticket's own scope;
  it is downstream of issue #559.
- **Per-platform cold-start install** (the actual warning dialogs, the actual bypass clicks) is
  tracked and blocked separately per platform: issue #590 (Windows), issue #592 (macOS). Linux
  has run for real (`M7-PACK-DEPLOY-139.md`).
- **Signing and notarisation are out of scope by design** (`M7-TAURI-DEPLOY-184a`, deferred,
  blocked on the cost of an Apple Developer enrolment) — not tested here because there is
  nothing to test yet.
