# Release procedure

How an Askwell version becomes a downloadable release. `M7-TAURI-DEPLOY-184`.

**Signing is not part of this.** Askwell ships unsigned — `docs/decisions.md`
(2026-08-26, "No trademark, unsigned distribution, and Apache-2.0 stays") settled that on
cost, not on engineering, and it is not reopened here. Real signing is `M7-TAURI-DEPLOY-184a`,
deferred and blocked on a purchase.

**What this procedure cannot yet do.** No pipeline produces a real installable bundle per
platform — `web/src-tauri/tauri.conf.json` has `bundle.active: false`, and issue #559 tracks
building one. Today's release artefact is the trimmed-repository tarball layout
`deploy/linux/install.sh`'s own header describes (compose stack, `deploy/`, the built shell
binary, the native inference binary), one per platform, assembled by hand or by a future CI
job once #559 lands. This procedure covers what happens **after** the artefacts exist —
checksumming and publishing them — not producing them. Do not treat a release built this way
as proof the installers work end to end on a clean machine; that walkthrough is still blocked
on #559, and separately on real macOS/Windows test hardware (#590, #592).

---

## 1. Confirm the version

`VERSION` at the repo root is canonical (`AGENTS.md` §7). Confirm it already reflects the
release — bumping it is part of the change that earns the release, not a separate step here.

```
cat VERSION
```

Check the top entry of `CHANGELOG.md` matches.

## 2. Assemble the artefacts

For each platform being released, build the trimmed tarball layout `deploy/<platform>/install.sh`
expects (see that script's header comment for the exact file list) and place every artefact for
the release into one directory, e.g. `dist/askwell-<version>/`:

```
askwell-<version>-linux.tar.gz
askwell-<version>-windows.zip
askwell-<version>-macos.tar.gz
```

Naming is illustrative — match whatever the packaging step actually produces once #559 exists.
**Do not publish a partial platform set silently** — if a platform's artefact could not be
built, that is a release blocker to raise, not a reason to ship the other two quietly.

## 3. The restore gate

Before checksumming or publishing anything, run `docs/restore-release-test.md` for this
`VERSION` and record the result in `docs/restore-test-log.md`. **A failed run blocks the
release** — this is a gate, not an aside (`M7-BACKUP-TEST-159`; `AGENTS.md` §3 "a release with
a failed restore test does not ship"). Do not proceed to step 4 without a `pass` entry for this
exact version.

## 4. Generate checksums

```
scripts/release-checksums.sh dist/askwell-<version>/
```

This writes `SHA256SUMS` into that directory, one line per artefact, and refuses to run
against an empty directory (an empty `SHA256SUMS` is indistinguishable from "verified" at a
glance, and only step 2 having actually produced something makes that true). Read the printed
output before continuing — it lists exactly what will be published.

## 5. Publish

Create the GitHub release and upload every artefact **and** `SHA256SUMS` itself:

```
gh release create v<version> dist/askwell-<version>/* \
  --title "Askwell <version>" \
  --notes-file docs/release-notes-template.md
```

`docs/release-notes-template.md` links `docs/installing.md` prominently, above the artefact
list — the same ordering `docs/installing.md` itself uses (verification before the bypass) and
for the same reason: **the checksum is the part that actually protects anyone**, and it must not
be buried under a changelog.

Do not edit the notes to move that link down or drop it. If the template needs changing, that
is a decision — log it in `docs/decisions.md` the way any change to `installing.md`'s ordering
already must be (`docs/decisions.md`, 2026-08-26).

## 6. Verify from outside the build

Before telling anyone the release is up, download it fresh — not from the build directory —
and check it against the published `SHA256SUMS`, exactly as `docs/installing.md` instructs a
user to:

```
shasum -a 256 -c SHA256SUMS   # or: sha256sum -c SHA256SUMS
```

A mismatch here means the upload is broken, not that anything was tampered with — but it is
the same check a suspicious user will run, so it must pass before the release is announced
anywhere.

## 7. Cold-start install verification

`docs/installing.md`'s instructions must be followed exactly, as written, on a machine that
has never seen Askwell, for each platform. This is a manual walkthrough, not something this
procedure can automate on a single build host:

- **Linux:** covered by `docs/manual-tests/M7-PACK-DEPLOY-139.md`.
- **Windows:** covered by `docs/manual-tests/M7-PACK-DEPLOY-140.md`; issue #590 tracks that a
  real clean-machine run has not happened yet.
- **macOS:** covered by `docs/manual-tests/M7-PACK-DEPLOY-141.md`; issue #592 tracks the same
  gap for macOS.

**Do not publish a release as verified without these having actually run.** A release that
skips this step is shipping the honest-unsigned promise (`docs/installing.md`) without having
checked it holds.

---

## What a release records

Per `AGENTS.md` §8, anything worth a future reader knowing is a decision or an issue, not a
release-note aside:

- The version and what changed: `CHANGELOG.md`, already current by step 1.
- Any platform skipped or any step that failed and was worked around: a GitHub issue,
  filed at the time, not folded into the next session's memory.
- No signing identity, credential or certificate expiry is recorded here — there is none yet.
  When `M7-TAURI-DEPLOY-184a` lands, this section gains that record.
