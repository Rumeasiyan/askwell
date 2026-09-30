# M11 — It answers on every platform

**Goal:** An installed Askwell answers a question on Windows, not only on Linux, and a spreadsheet question reaches the spreadsheet.

**Phase:** 7 (`../build-plan.md`) · **Depends on:** M10 · **Tickets:** 2 to start; the C5 ticket is added once the GPU experiment (`M10-FIX-DEPLOY-222` made it possible) has a result · **Estimated:** 11 hours

**Exit condition:** On the Windows test VM (`scripts/winvm.sh`, #836), a fresh install downloads the model and answers a question with a citation. `figures-logistics-headcount`, `figures-design-headcount` and `figures-retail-headcount-paraphrase` in `grounded_qa.v1` score above 0.

> **Where these came from.** The Windows test VM ran Setup end to end for the first time on 2026-09-30. After ten installer fixes (branch `fix/setup-compose-before-machine`), Askwell installs, every container runs and the window opens. It still cannot answer anything, because the inference bridge was built for Linux (#845). The spreadsheet ticket is the half of #818 that `M10-FIX-BE-220` showed is not routing (#827).

---

### M11-FIX-DEPLOY-223 — The containers reach the AI on Windows

**Type:** Task

**User Story**
- **Actor:** anyone who installs Askwell on Windows.
- **User Need:** to ask a question and get an answer.
- **Business Value:** today an installed Askwell on Windows opens, downloads its model, and then cannot answer anything.

**Context / Background**
**Detailed Description:** Read #845, including its comments. The first version of this ticket assumed `host.containers.internal` would reach the PC; the build agent tested it on the Windows VM and it does not (it resolves back into the WSL VM). The orchestrating session then tested WSL **mirrored networking** on the same VM on 2026-09-30:
- **Test:** `%USERPROFILE%\.wslconfig` with `[wsl2]` and `networkingMode=mirrored`, then `wsl --shutdown`, then `podman machine start`. A Windows process listens on `127.0.0.1:18080`, and a container on `--network host` dials it.
- **Result:** default NAT, `Connection refused`. Mirrored, HTTP `200`.

So the design is: **on Windows, WSL runs in mirrored networking mode, and the bridge keeps dialling `127.0.0.1` exactly as on Linux.** `UPSTREAM_HOST` and C1's reading of the bridge do not change. That is why this beat the alternatives: a firewall hole for the WSL subnet, a vsock relay, or llama.cpp inside the VM without the GPU.

Two changes remain.
1. **The sockets.** The bridge's Unix socket, and the worker-unlock socket (`api/src/askwell/worker_unlock.py`), cannot live on a bind mount of a Windows directory: drvfs has no Unix sockets (`Errno 95`). Put the sockets on a named volume shared by the containers that use them. Keep the files the host supervisor writes (its status) on the existing bind mount, because the host must reach them. On Linux, nothing changes by default.
2. **Setup.** Before the Podman machine is created or started, `setup-bootstrap.ps1` makes sure `%USERPROFILE%\.wslconfig` has `networkingMode=mirrored` under `[wsl2]`. It edits the file rather than replaces it, keeps every other setting, and says in its log exactly what it changed. When it changed anything and a machine is already running, it runs `wsl --shutdown` and starts the machine again. Mirrored mode needs Windows 11 22H2 (build 22621) or newer. Setup refuses older builds with a clear message and its own exit code. Windows 10 has passed its end of support, and Askwell never worked on it.

**Scope**
- The socket paths become settings. `compose.yaml` gains a named volume for them; Linux keeps its current paths by default.
- `.wslconfig` handling in `lib.ps1` is pure and tested (merge into an existing file, add the section, leave other keys, idempotent). `setup-bootstrap.ps1` calls it.
- The build check, with its own exit code and a report meaning (`Get-AskwellSetupCodeMeaning`).
- `docs/decisions.md` entry: mirrored networking, what was tested, and what was rejected and why.

**Out of Scope**
- macOS, which needs its own verified answer (#592); file a follow-up.
- Any change to `UPSTREAM_HOST` or C1.

**Acceptance Criteria**
- **Acceptance Criteria:** `install.test.ps1` covers the `.wslconfig` merge. `setup-bootstrap.test.ps1` gains scenarios for "mirrored set, machine restarted" and "Windows too old: refused". `scripts/dev.sh test`, `test-db` and the Windows CI pass. The end-to-end run on the Windows VM is the orchestrating session's, not the agent's: fresh install, model download, and a question answered with a citation. Leave `docs/manual-tests/M11-FIX-DEPLOY-223.md` with the steps and an empty result.
- **Edge Cases:** `.wslconfig` already has `networkingMode=nat`, which is changed, and the log says so. It is UTF-16, which is read and written back correctly. It has `[wsl2]` with other keys, which are kept.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** unchanged.
- **Validation Rules:** C1 unchanged; `inference-bridge` still dials only `127.0.0.1`. C8: nothing secret added.
- **Audit / Logging Requirements:** Setup logs the `.wslconfig` change. The bridge logs its socket path at start.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** `M10-FIX-DEPLOY-222`; the Windows installer as of `0.9.10`.
- **API / Data Touchpoints:** `api/src/askwell/inference/bridge.py`, `api/src/askwell/inference/client.py`, `api/src/askwell/worker_unlock.py`, `compose.yaml`, `deploy/windows/lib.ps1`, `deploy/windows/setup/setup-bootstrap.ps1`, `deploy/windows/install.ps1`.
- **Assumptions:** Podman's own port publishing (`127.0.0.1:8000` for the API) still reaches Windows in mirrored mode. The orchestrating session checks this in the end-to-end run.

**Testing Notes / Scenarios**
- **Windows walkthrough (not the agent's):** `scripts/winvm.sh reset && scripts/winvm.sh start`, install a Setup built from this branch, download the model from the setup screen, add `eval/fixtures/corpus`, and ask "What is the notice period in handbook A?"

**Effort & Granularity Check**
- **Estimate:** 6 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, `deploy`, `constraint:local-first`
- **Granularity:** One networking mode and one socket move.

---

### M11-FIX-ING-224 — A spreadsheet's rows can be queried like a table

**Type:** Task

**User Story**
- **Actor:** anyone who adds an Excel workbook.
- **User Need:** "How many people work in Logistics?" answered from the sheet.
- **Business Value:** three of the remaining `grounded_qa.v1` failures are spreadsheet questions phrased differently from the column headings, and a table query answers them exactly where passage retrieval cannot.

**Context / Background**
**Detailed Description:** Read #827. `.xlsx` is routed to documents only (`askwell.filetypes`), so no schema note exists for a workbook and `M10-FIX-BE-220`'s table fallback has nothing to fall back to. CSV already loads as a table (`M4-CSV-ING-094`). Load each sheet of a workbook the same way CSV is loaded, keeping its document chunks as they are, so a workbook is both searchable and queryable.

**Scope**
- Each non-empty sheet with a header row becomes a table, alongside the existing document ingestion.
- Schema notes are created as for CSV.
- A sheet without a recognisable header row is skipped for tables and still ingested as a document.

**Out of Scope**
- Formulas, merged cells and charts. Cached values only.
- Changing the retrieval threshold (C5 — not lowered to improve a number).

**Acceptance Criteria**
- **Acceptance Criteria:** Tests first, for header detection and for the sheet-to-table load. `grounded_qa.v1` run alone on `llama-server`: the three tasks named above score above 0, and nothing that passed before regresses. Record both in `../BRAIN.md`, honestly, whatever it shows. The eval can exceed one build-agent hour (`docs/operating-the-build.md`); if it does not finish, say so and leave it for the orchestrating session rather than claiming a number.
- **Edge Cases:** a 100k-row sheet (bounded load, the same limit as CSV); a sheet whose name is not a valid identifier; two sheets with the same headers.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** `../ux/add-source.md` — a workbook shows as one source.
- **Validation Rules:** C2 unchanged: every query is still validated by `askwell.sql.validate`. C3 unchanged: workbook tables load into the sandbox, not Askwell's database.
- **Audit / Logging Requirements:** tables created per sheet, logged with the source id.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** `M4-CSV-ING-094`, `M10-FIX-BE-220`.
- **API / Data Touchpoints:** `api/src/askwell/filetypes.py`, the CSV loader, schema notes.
- **Assumptions:** the CSV loader can take rows from a sheet reader without a second code path. If it cannot, say so.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** add `eval/fixtures/corpus/figures.xlsx` and ask "How many people work in the Logistics department?"
- **Known gaps:** close #827 with the recorded numbers, and #818 with it.

**Effort & Granularity Check**
- **Estimate:** 5 hours · **Priority:** High
- **Labels / Component:** `phase:7`, `constraint:grounding`, `constraint:sandbox`, backend
- **Granularity:** One loader reused for one more file type.

---

> **Added 2026-09-30, after the first end-to-end run of the real `0.9.11` release on the Windows test VM.** Setup installed Askwell from a clean Windows 11 through the restart, and every service came up. With the models in place, the AI came up only after three manual steps and one clock correction. A question then reached `/ask` and completed. Adding a folder failed outright. The three tickets below are what that run found. Evidence is in the tickets; the run itself used `scripts/winvm.sh`.

### M11-FIX-DEPLOY-225 — The AI supervisor starts with Askwell's settings on every platform, and on Windows with a runtime it can use

**Type:** Task

**User Story**
- **Actor:** anyone who installs Askwell, on any platform.
- **User Need:** the assistant starts once the model is in place, with nothing to set up by hand.
- **Business Value:** today the assistant never starts on an installed Askwell on **Linux or Windows**, and very likely macOS. Neither the user nor `/health` sees why.

**Context / Background**
**Detailed Description:** Two defects, both found on the Windows VM with `0.9.11`.
1. **No Visual C++ runtime.** Every bundled `llama-server.exe` (the GPU and the CPU build) exits with `3221225781` (`0xC0000135`, a DLL not found). A new Windows has no `vcruntime140.dll`, `msvcp140.dll` or `vcruntime140_1.dll`. The VM test: installing Microsoft's `https://aka.ms/vs/17/release/vc_redist.x64.exe` with `/install /quiet /norestart` gives exit 0, after which `llama-server.exe --version` runs. The file is Authenticode-signed by `CN=Microsoft Corporation` (status `Valid`). It is a moving permalink, so there is no fixed SHA-256 to pin; verify the signature instead (`Get-AuthenticodeSignature`: status `Valid`, signer subject begins `CN=Microsoft Corporation,`). Setup installs it when those three DLLs are missing, before Askwell itself, and the success codes are 0, 3010 and 1638 (a newer version is already installed). It is downloaded at install time, not bundled, like Python and WSL, so C9 is not engaged.
2. **The supervisor has no settings, on every platform.** On a clean Ubuntu 24.04 VM, a fresh `0.9.11` install shows the same defect. `~/.config/systemd/user/askwell-inference.service` has no `EnvironmentFile=` and no `WorkingDirectory=`. The journal shows `No model file at .` and `could not write state: [Errno 13] Permission denied: '/run/askwell'`, while the stack itself came up and `/health` answered. Loading `.env` alone is not enough, because `.env`'s `ASKWELL_INFERENCE_SOCKET` is the **containers'** path, `/run/askwell/inference.sock`. The supervisor must write its state into the host directory the containers mount there: `ASKWELL_RUN_DIR` (default `./.run`), resolved against the app directory. The developer path works only because `scripts/dev.sh inference` sets the socket explicitly. On Windows, the `AskwellInference` scheduled task runs `pythonw.exe askwell-inference` with no environment, so the supervisor saw no `ASKWELL_INFERENCE_MODEL_PATH` ("No model file at .") and took `ASKWELL_INFERENCE_SOCKET`'s default, `/run/askwell/inference.sock`. On Windows that is `C:\run\askwell`, so it wrote its `state.json` there. The API reads `<app>\.run\state.json`. On Linux the systemd unit loads `.env`; on Windows nothing does. Give `askwell-inference` an `--env-file PATH` option: it loads the file without overriding variables already set, and derives its socket and state paths from `ASKWELL_RUN_DIR` resolved against the `.env` file's directory, not from the container path. Every installer passes it: the systemd unit on Linux (plus `WorkingDirectory=`), the launchd agent on macOS, and `Get-AskwellInferenceTaskArguments` on Windows. Verified by hand on the VM: with the `.env` loaded and the socket under `<app>\.run`, all three roles reported `ready` and `/health` showed inference reachable.

**Scope**
- The VC++ runtime step in `setup-bootstrap.ps1`: a signature check, a new exit code, and a `Get-AskwellSetupCodeMeaning` entry.
- `--env-file` in `deploy/inference/askwell-inference`, tested, including the run-directory derivation.
- The Linux systemd unit, the macOS launchd agent and the Windows task arguments, each tested in its platform's `install.test.*`.

**Out of Scope**
- The desktop app starting its own supervisor (`M11-FIX-SHELL-226`).

**Acceptance Criteria**
- **Acceptance Criteria:**
  - `install.test.ps1` covers the task arguments and the signature-check helper.
  - `setup-bootstrap.test.ps1` gains three scenarios: runtime missing, which installs it; a signature that is not Microsoft's, which is refused and never run; and runtime present, which skips the step.
  - The supervisor's `--env-file` has unit tests. The file must not override variables already set.
  - Windows CI and `scripts/dev.sh check` pass.
  - The VM walkthrough is the orchestrating session's; leave `docs/manual-tests/M11-FIX-DEPLOY-225.md` with an empty result.
- **Edge Cases:** VC++ already present in a newer version (1638). `.env` lines with `=` inside values. A `~` in a path, expanded as the supervisor already does.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** unchanged.
- **Validation Rules:** C1: the runtime download is install-time and user-initiated, like winget's. C8: `.env` is read, never logged.
- **Audit / Logging Requirements:** Setup logs the runtime's version and signer.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** `M11-FIX-DEPLOY-223`.
- **API / Data Touchpoints:** `deploy/windows/setup/setup-bootstrap.ps1`, `deploy/windows/lib.ps1`, `deploy/windows/install.ps1`, `deploy/inference/askwell-inference`.
- **Assumptions:** none untested; both halves were verified by hand on the VM.

**Testing Notes / Scenarios**
- **Walkthroughs (not the agent's):** a clean Windows VM (`scripts/winvm.sh`) and a clean Ubuntu 24.04 VM, each with the models placed. `/health` must show inference reachable with no manual step.

**Effort & Granularity Check**
- **Estimate:** 5 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, `deploy`
- **Granularity:** Two installer defects on one path to "the assistant starts".

---

### M11-FIX-SHELL-226 — The desktop app never starts a second AI supervisor, and "is it alive" does not compare two machines' clocks

**Type:** Task

**User Story**
- **Actor:** anyone running Askwell on Windows or macOS.
- **User Need:** no stray console window, and an assistant that is not reported dead while it is running.
- **Business Value:** a visible `python.exe` console that closes Askwell's AI when the user closes it. Two supervisors fighting over one port. A working assistant reported as "stopped reporting".

**Context / Background**
**Detailed Description:** Two defects, found on the Windows VM.
1. **A second supervisor.** `spawn_inference` in `web/src-tauri/src/supervisor.rs` starts its own `python askwell-inference` whenever it sees no fresh heartbeat. At sign-in the `AskwellInference` scheduled task is starting at the same moment and has not written one yet, so the app starts a second supervisor. On Windows it is a plain `python.exe` without `CREATE_NO_WINDOW`, so it shows a console window. Fix: before its first spawn, the app waits one heartbeat interval plus a margin for a supervisor to appear. On Windows it spawns with `CREATE_NO_WINDOW` (`std::os::windows::process::CommandExt`). The candidates stop at the first real Python (the Store's `WindowsApps` placeholder is never used, as in `Get-AskwellPython`).
2. **Two clocks.** The API calls the supervisor stale when `now - state.updated_at` exceeds a limit. `now` is the container's clock, inside Podman's VM, and `updated_at` is the host's. On the VM the WSL clock ran about 7 hours ahead of Windows, and a `ready` supervisor was reported as "stopped reporting" until the clock was corrected by hand. WSL clock drift after sleep is also a known real-world problem. Fix: the API judges freshness by when *it last saw `state.json` change*, on its own clock. It never compares a timestamp written on another machine. Keep `updated_at` in the file for people reading it.

**Scope**
- `supervisor.rs`: the grace period, `CREATE_NO_WINDOW` and the candidate order, with Rust unit tests for the pure parts.
- `api/src/askwell/inference/state.py` (or wherever staleness is computed): freshness by observed change, tested with a fake clock and a `state.json` whose `updated_at` is hours off.

**Out of Scope**
- The supervisor's settings on Windows (`M11-FIX-DEPLOY-225`).

**Acceptance Criteria**
- **Acceptance Criteria:**
  - Tests: a heartbeat file 7 hours "in the future" and changing is fresh, and one not changing for longer than the limit is stale.
  - The app does not spawn while a supervisor heartbeat appears within the grace period.
  - `cargo check`, `scripts/dev.sh check` and `test-db` pass.
- **Edge Cases:** No supervisor at all, where the app still starts one after the grace period, as today. The API started before the supervisor.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** `../ux/ask.md` — the assistant states are unchanged; only when "stale" is decided changes.
- **Validation Rules:** None new.
- **Audit / Logging Requirements:** the app logs when it defers to an existing supervisor.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** `M11-FIX-DEPLOY-223`.
- **API / Data Touchpoints:** `web/src-tauri/src/supervisor.rs`, `api/src/askwell/inference/state.py`, `api/src/askwell/health.py`.
- **Assumptions:** the heartbeat interval is `HEARTBEAT_SECONDS` in `deploy/inference/askwell-inference`; read it, do not guess it.

**Testing Notes / Scenarios**
- **Windows walkthrough (not the agent's):** sign in to the VM after an install. Exactly one `askwell-inference` process runs, and no console window appears.

**Effort & Granularity Check**
- **Estimate:** 5 hours · **Priority:** High
- **Labels / Component:** `phase:7`, desktop shell, backend
- **Granularity:** Two liveness defects in one handshake.

---

### M11-FIX-BE-227 — Askwell can read the user's own folder on every platform, and Windows paths work

**Type:** Task

**User Story**
- **Actor:** anyone who adds a folder of documents after installing Askwell.
- **User Need:** pick a folder and have it indexed, with no configuration file.
- **Business Value:** today a new install on any platform cannot index anything until `ASKWELL_ROOTS_MOUNT` is edited by hand in `.env`. On Windows a folder is refused outright: `POST /sources` answered 400, *"Askwell needs the whole path, starting with a slash - 'C:\Users\askwell\Documents\corpus' is relative to something"* (found on the VM).

**Context / Background**
**Detailed Description:** **Decided by the owner on 2026-09-30: Askwell may read the user's whole home folder, read-only.** That means `C:\Users\<name>` on Windows, `/Users/<name>` on macOS and `$HOME` on Linux. The alternative, only the folders the user picks with a stack restart per new location, was declined as slower and more fragile for non-technical users. Record it in `docs/decisions.md` with that reasoning and what it widens: the containers still have no route off the machine, and the mount stays read-only.
1. **All platforms.** Each installer sets `ASKWELL_ROOTS_MOUNT` to the user's home in `.env`, on install and on upgrade when it is empty. A value the user already set is left alone.
2. **Windows.** `compose.yaml` mounts roots at the *same path* inside the container, which is impossible for `C:\...`. Introduce one translation, in one place: a Windows host path `C:\Users\n\x` maps to a fixed container path (for example `/host/c/Users/n/x`), and back. The mount becomes `C:\Users\n` → `/host/c/Users/n` on Windows only. `sources.root_path` and `documents.path` keep the **Windows** path, which is what the user sees and what a citation reopens. Every place the API or worker touches the filesystem goes through the translation, which is the identity on Linux and macOS. Path validation accepts `X:\...` on Windows. The compose file's comment on why identity mattered is updated, not deleted.

**Scope**
- The installers' `.env` step on three platforms, tested in each `install.test.*`.
- `askwell.paths` (or similar): one translation function each way, pure and tested, including case-insensitive drive letters and `/` and `\` separators.
- Path validation for Windows paths, with a test for the exact 400 above.

**Out of Scope**
- A folder picker that grants access per folder (declined).
- Paths outside the home folder: a clear refusal naming the reason, not new mounts.

**Acceptance Criteria**
- **Acceptance Criteria:**
  - Unit tests for the translation both ways and for validation.
  - A `requires_db` test adds a folder whose host path is Windows-shaped, through the translation, and indexes it.
  - The three installer suites and Windows CI pass.
  - The VM walkthrough is the orchestrating session's: add `C:\Users\askwell\Documents\corpus` and ask "What is the standard resignation notice period at Meridian Loom?" The answer must cite the handbook. Leave `docs/manual-tests/M11-FIX-BE-227.md` with an empty result.
- **Edge Cases:** Paths with spaces and non-ASCII letters. A UNC path (`\\server\share`), refused clearly. A folder on another drive (`D:\`), refused, naming why.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** `../ux/add-source.md` — the "not mounted" state now appears only outside the home folder.
- **Validation Rules:** C1 unchanged: no network in the containers. The mount stays read-only.
- **Audit / Logging Requirements:** the effective roots mount is logged at API start.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** `M11-FIX-DEPLOY-223`.
- **API / Data Touchpoints:** `compose.yaml`, `api/src/askwell/roots.py`, `api/src/askwell/sources.py`, the worker's file reads, `deploy/*/install.*`, `deploy/windows/lib.ps1`.
- **Assumptions:** Podman on WSL accepts a Windows-path bind source (`C:\Users\n:/host/c/Users/n:ro`). The `.run` and models mounts already do, on the VM.

**Testing Notes / Scenarios**
- **Known gaps:** macOS is unverified on hardware (#592).

**Effort & Granularity Check**
- **Estimate:** 6 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, backend, `deploy`, `constraint:local-first`
- **Granularity:** One mount default and one path translation.
