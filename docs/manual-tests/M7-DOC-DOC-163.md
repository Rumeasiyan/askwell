# Manual test — M7-DOC-DOC-163, licence and notices file for bundled model weights

**Ticket:** `M7-DOC-DOC-163` — `NOTICES.md` listing every bundled model weight and every code
dependency with its licence, a check that fails the release gate on a disallowed licence, and
the file reachable from the product's Settings → About section.
**Version under test:** `0.7.17`
**Time:** about 20 minutes. No native inference process required — nothing here touches
retrieval or generation.

**What is being checked.** `api/src/askwell/notices.py` (the static `MODEL_NOTICES` table and
`disallowed_tokens`), `scripts/generate_notices.py` (regenerates `NOTICES.md` from what is
actually installed, exits 1 on a disallowed licence), `web/components/settings/about.tsx` (the
About section, reachable from Settings) and `web/scripts/copy-notices.mjs` (copies the
repository's `NOTICES.md` into `web/public/notices.md` at build time, which the About section
links to).

**Human review required.** This ticket renders wording a user reads (`docs/ux/settings.md` §7).
Flag the exact About-section copy for review before this PR merges.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env`, find `POSTGRES_APP_PASSWORD`, and put any word after the `=` if it is blank.

---

## Cold start

### 1. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started.
Wait about thirty seconds.

### 2. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 3. Open Askwell in a browser

```
http://127.0.0.1:8000
```

**You should see:** the app loads — first-run or the composer, depending on whether a source
has been added before.

### 4. Navigate to Settings by clicking, not by URL

Click **Settings** in the left navigation rail (below **Ask**, **Library**,
**Clarifications**, **Memory**).

**You should see:** the Settings screen, with sections for Hardware profile, Folders, Retrieval
threshold, Storage, Privacy & security, Your data, and — at the bottom — **About**.

### 5. Read the About section

Scroll to the bottom of Settings.

**You should see:** a definition list with five rows:

- **Version** — `0.7.17` (matches `VERSION` at the repo root — check with `cat VERSION`)
- **Licence** — `Apache-2.0`
- **Source** — a link reading `https://github.com/Rumeasiyan/askwell`
- **Report a problem** — a link labelled "Open an issue"
- **Notices** — a link labelled "Third-party notices and licences"

### 6. Open the notices link

Click **"Third-party notices and licences"**.

**You should see:** it opens `http://127.0.0.1:8000/notices.md` in a new tab as plain text (or
your browser's Markdown-as-text rendering), starting with `# Third-party notices`.

### 7. Confirm every bundled model is listed with a licence and a source

In that document, find **## Bundled model weights**.

**You should see:** a table with these rows, each with a non-empty Licence and Source column:

| Role | Model | Licence |
| ---- | ----- | ------- |
| Generation (light, standard) | Qwen3.5 4B (Q4_K_M) | Apache-2.0 |
| Generation (accelerated, workstation) | Qwen3.5 9B (Q4_K_M) | Apache-2.0 |
| Embedding | bge-m3 | MIT |
| Reranker | bge-reranker-v2-m3 | Apache-2.0 |
| Transcription | Whisper small (CTranslate2) | MIT |
| Voice activity detection | Silero VAD | MIT |
| Synthesis | Kokoro-82M | Apache-2.0 |
| OCR engine | Tesseract | Apache-2.0 |
| OCR traineddata (English) | tesseract-ocr-eng | Apache-2.0 |
| OCR traineddata (orientation/script) | tesseract-ocr-osd | Apache-2.0 |
| OCR traineddata (Tamil) | tesseract-ocr-tam | Apache-2.0 |

None carries a `GPL`, `AGPL`, `SSPL`, `CC-BY-NC`, or "unlicensed"/proprietary token — the
disallowed set in `api/src/askwell/notices.py`.

### 8. Confirm the licence restrictions that don't fit a standard SPDX name are recorded verbatim

Look at the **Note** column for the `bge-m3` and `bge-reranker-v2-m3` rows.

**You should see:** the note is written out in full — "No automated, registry-verified fetch
path yet — placed manually, tracked in #244." — not summarised or dropped. This is the ticket's
own edge case ("recorded verbatim rather than summarised, since summarising a licence is how a
restriction gets lost") applied to the one caveat currently on file; no bundled model in this
distribution actually carries a *usage-restricted* licence today, so this is the closest
verification available.

### 9. Confirm the repository copy and the served copy match

```
diff NOTICES.md web/public/notices.md
```

**You should see:** no output — the file served to the browser in step 6 is a byte-for-byte
copy of the repository's own `NOTICES.md`, not a second hand-maintained copy.

---

## Part A — the notices generator, run against what is actually installed

### 10. Run the full notices pipeline

```
scripts/dev.sh notices
```

This runs `pnpm licenses list --json --prod` inside the web image, then
`scripts/generate_notices.py` inside the API image against that output.

**You should see:** `wrote /path/to/askwell/NOTICES.md` printed, followed by either
`no disallowed licences found` (exit 0) or a `DISALLOWED LICENCES FOUND` block naming the
offending package (exit 1) — check with `echo $?` after the command finishes.

**As of this writing, the known state is exit 1.** `docs/release-procedure.md` §3b records that
`kokoro-onnx` pulls in `phonemizer` (GPLv3-or-later), tracked in issue #619 and not yet
resolved. Confirm this is the failure you see, not a new one:

```
scripts/dev.sh notices 2>&1 | grep -i phonemizer
```

**You should see:** a line naming `phonemizer` and `GPL-3.0-OR-LATER` (or `-only`). If the
output names any *other* package or model, that is a new, previously unrecorded finding — file
it, do not fold it into #619.

### 11. Confirm the regenerated file is committed

```
git diff --stat NOTICES.md
```

**You should see:** either no diff (the checked-in file already matches what
`scripts/dev.sh notices` just produced) or a diff reflecting a real, expected change — a stale
`NOTICES.md` that is out of sync with `pyproject.toml`/`package.json` is itself the bug this
generator exists to prevent.

---

## Part B — the disallowed-licence check, exercised directly

Since the release-gate script needs a full container rebuild to add a dependency, exercise the
same matching logic the ticket's acceptance criteria asks for directly through its test suite —
this is the fast, repeatable form of "add a dependency with a disallowed licence on a branch and
confirm the check fails":

### 12. Run the unit suite for the notices module

```
scripts/dev.sh test api/tests/test_notices.py -v
```

**You should see:** all tests pass, including:

- `test_every_model_notice_has_a_licence_and_a_source`
- `test_no_bundled_model_carries_a_disallowed_licence`
- `test_model_notices_cover_every_bundled_role`
- `test_disallowed_tokens_matches_plain_gpl_and_agpl`
- `test_disallowed_tokens_never_flags_lgpl_via_substring`
- `test_disallowed_tokens_matches_within_a_compound_expression`

### 13. Prove a disallowed licence actually fails the check, live

```
scripts/dev.sh run python -c "
from askwell.notices import disallowed_tokens
print(disallowed_tokens('GPL-3.0-or-later'))
print(disallowed_tokens('MIT'))
print(disallowed_tokens('LGPL-3.0-only'))
"
```

**You should see:**

```
['GPL-3.0-OR-LATER']
[]
[]
```

The first is caught, MIT is not flagged, and LGPL (weak copyleft, deliberately not on the
disallowed list per `api/src/askwell/notices.py`'s own docstring) is not caught by substring
accident.

### 14. Confirm the release-gate script itself would exit non-zero on this repository's real state

Already shown in step 10 — `scripts/dev.sh notices` exits 1 today because of the `phonemizer`
finding. This *is* "the check fails the build" the ticket's cold-start walkthrough asks for; a
synthetic disallowed dependency does not need to be added separately, since a real one is
already present and the exit code already reflects it.

---

## Part C — a transitive dependency with unclear licence metadata is flagged, not assumed permissive

### 15. Confirm the UNVERIFIED path exists for packages with no machine-readable licence

```
grep -n "UNVERIFIED" api/src/askwell/../../../scripts/generate_notices.py
```

**You should see:** `_python_license` returns `"UNVERIFIED"` (or
`"UNVERIFIED (raw metadata: ...)"`) rather than defaulting to a permissive guess when a package
publishes no `License-Expression`, no matching classifier, and no usable `License` field — the
two known exceptions (`kokoro-onnx`, `espeakng-loader`) are hand-verified against their GitHub
repository's own licence API and recorded in `_KNOWN_LICENSE_OVERRIDES` with the verification
date in a comment, not silently assumed.

### 16. Check whether the current `NOTICES.md` contains any `UNVERIFIED` entry

```
grep -n UNVERIFIED NOTICES.md
```

**You should see:** no matches today (every shipped dependency in the current lockfiles carries
resolvable licence metadata) — this is a check for absence, confirming the flagging mechanism
exists and has nothing to flag right now, not proof it will stay empty as dependencies change.

---

## Known gaps

- **The release gate is currently red.** `phonemizer` (GPLv3-or-later, pulled in transitively by
  `kokoro-onnx`) is on the disallowed list, tracked in issue #619, unresolved as of
  `docs/release-procedure.md`'s own note (2026-09-23). Step 10 seeing a failure is expected, not
  a regression introduced by this ticket — do not report it as a new defect. Resolving #619
  (dropping the `phonemizer` dependency, replacing it, or a deliberate recorded exception in
  `docs/decisions.md`) is separate work.
- **No automated, registry-verified fetch path for `bge-m3` and `bge-reranker-v2-m3`.** Their
  licence entries are correct but were placed manually rather than verified through the same
  automated pipeline the other models use — tracked in issue #244, noted on both rows in
  `NOTICES.md` itself so it isn't rediscovered silently.
- **No live packet capture or GitHub-licence-API re-verification was performed here.** Step 8's
  and step 15's confirmations read the code and the generated file; they do not re-fetch each
  model's or package's registry entry live. `AGENTS.md` §4's registry-verification rule was
  applied when each row was written (dates in the `Verified` column), not re-run by this manual
  test.
- **No update-check control exists yet in About.** `docs/ux/settings.md` §7 also describes an
  opt-in weekly update check with a "check now" control; that is `M7-UPDATE-BE-161` (backend,
  done) and `M7-UPDATE-FE-162` (frontend, not yet built) — out of scope for this ticket and not
  present in `about.tsx`. Its absence in step 5 is expected, not a defect.
- **A user-swapped model's licence is not checked.** The ticket states this is explicitly the
  user's own responsibility (`about.tsx`'s own comment, `NOTICES.md`'s own caption text) — there
  is no mechanism here, nor should there be one, that inspects a model file a user substitutes
  themselves.
