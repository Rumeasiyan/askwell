# M11 — It answers on every platform

**Goal:** An installed Askwell answers a question on Windows, not only on Linux, and a spreadsheet question reaches the spreadsheet.

**Phase:** 7 (`../build-plan.md`) · **Depends on:** M10 · **Tickets:** 2 to start, 225–227 from the Windows VM run, and 228–234 added by `M11-FIX-ING-224` for what it left open; the C5 ticket is added once the GPU experiment (`M10-FIX-DEPLOY-222` made it possible) has a result · **Estimated:** 11 hours

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

3. **Linux: two missing packages.** On a clean Ubuntu 24.04 VM the installer installed Podman, then stopped, telling the user to install Docker Compose themselves. Ubuntu packages it as `docker-compose-v2`, which `podman compose` finds (`/usr/libexec/docker/cli-plugins/docker-compose`, 2.40.3). After that, every bundled `llama-server` failed with `libgomp.so.1: cannot open shared object file`. The fix is `apt-get install libgomp1`, after which all three roles reached `ready`. The Linux installer installs both through the package manager it already uses for Podman, in the same one `sudo` confirmation: `docker-compose-v2` and `libgomp1` on Debian/Ubuntu, `docker-compose` and `libgomp` on Fedora. With 1–3 in place, and folder access set as `M11-FIX-BE-227` will, that VM answered "What is the standard resignation notice period at Meridian Loom?" with "sixty-three days [1]".

**Scope**
- The Linux installer's package step: Docker Compose and the OpenMP runtime, tested in `install.test.sh` for apt and dnf.
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

---

> **Added 2026-09-30 by `M11-FIX-ING-224`,** for what it left open. Each one is filed as an issue too.

### M11-FIX-BE-235 — A fresh install gets every model it needs from the setup screen, and finds what it downloaded

**Type:** Task

**User Story**
- **Actor:** anyone who installs Askwell, on any platform.
- **User Need:** press Download once on the setup screen, and have Askwell answer questions afterwards.
- **Business Value:** today no fresh install can ever work. Found on a clean Ubuntu 24.04 VM with `0.9.15`, installed with no manual steps.

**Context / Background**
**Detailed Description:** Three defects, all on the first-run path. Every earlier test hid them, because the models were copied in by hand.
1. **Two of three models have no download.** `api/src/askwell/models_catalog.py` lists only the generation model per tier. The embedding model (`bge-m3`, the file `.env.example` names `bge-m3-FP16.gguf`) and the reranker (`bge-reranker-v2-m3-FP16.gguf`) have no catalog entry and no download, and the release bundles no `.gguf` at all (checked: `tar -tzf askwell-0.9.15-linux-x86_64.tar.gz | grep -c .gguf` is 0). Without them the supervisor's `embedding` and `reranking` roles stay `model_missing`, and nothing can be indexed or searched. Add both to the catalog. **Verify each against the registry before writing it down (`AGENTS.md` §4):** repo, file, size, SHA-256, licence (C9: GPLv3-compatible, redistributable, commercial use) and gating. The setup screen's one Download fetches all the models the tier needs, and shows one total. The stated size changes from "about 3 GB" to the real total.
2. **The downloaded file is not the file looked for.** The catalog downloads `Qwen_Qwen3.5-4B-Q4_K_M.gguf` (bartowski's name), while every installer's `.env` and `.env.example` point `ASKWELL_INFERENCE_MODEL_PATH` at `.../Qwen3.5-4B-Q4_K_M.gguf`. On the VM, the download finished (`status: ready`, checksum verified), the file was in place, and the supervisor went on reporting `No model file at .../Qwen3.5-4B-Q4_K_M.gguf` indefinitely. Make one source of truth. The installers write the catalog's filenames for the chosen tier, and the verify-manual path accepts a file by checksum whatever its name, as it already claims to.
3. **A supervisor that found a model missing never looks again.** Roles that reported `model_missing` at start stayed there after the files arrived, until a restart. When a download or a verify-manual completes, the supervisor must (re)start the affected roles; check whether the existing swap signal already carries this. It must also re-check a missing model on a modest interval, so a file placed by hand is picked up without a restart.

**Also found, for the record:** this build machine's evals ran against a *different* 4B file (2,740,937,888 bytes, not the catalog's 3,013,027,808). Askwell's own verify-manual rejects it as unrecognised. So `docs/BRAIN.md`'s eval baseline was measured on a model users never get. Say so in `BRAIN.md`, and leave the re-measurement to the orchestrating session.

**Scope**
- The catalog: two new roles, each with registry-verified metadata.
- The setup download of all of a tier's models, with progress totalled.
- The installers' `.env` model paths on all three platforms, matching the catalog.
- The supervisor re-checking and starting roles when models arrive.

**Out of Scope**
- Changing which models Askwell uses.

**Acceptance Criteria**
- **Acceptance Criteria:**
  - Tests: every catalog entry has a size, a SHA-256 and a licence; the installers' `.env` paths equal the catalog filenames for the default tier; a role that was `model_missing` starts when its file appears (with a fake clock and a fake `llama-server`).
  - `scripts/dev.sh check`, `test-db` and the installer suites pass.
  - The clean-VM walkthrough is the orchestrating session's. Leave `docs/manual-tests/M11-FIX-BE-235.md` with an empty result.
- **Edge Cases:** An interrupted download of one of three models, which resumes, as today. A model already present with the right checksum, which is not downloaded again. Disk space too small for the total, refused before starting, naming the total.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** `../ux/` setup screen, where the progress and size copy change.
- **Validation Rules:** C1: the download stays an explicit user action on the setup screen. C9: each new model's licence is verified and recorded in `api/src/askwell/notices.py`.
- **Audit / Logging Requirements:** each model's verified checksum is logged on completion.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** `M11-FIX-DEPLOY-225`.
- **API / Data Touchpoints:** `api/src/askwell/models_catalog.py`, `api/src/askwell/setup.py`, `deploy/inference/askwell-inference`, `deploy/*/install.*`, `.env.example`, `api/src/askwell/notices.py`.
- **Assumptions:** the `bge-m3` and `bge-reranker-v2-m3` GGUF files the supervisor already runs are published by an ungated, verified uploader. If they are not, say so and stop.

**Testing Notes / Scenarios**
- **Clean-VM walkthrough (not the agent's):** on a fresh Ubuntu 24.04 VM, install, press Download (`POST /setup/model/start`), nominate and add `eval/fixtures/corpus`, and ask "What is the standard resignation notice period at Meridian Loom?" The answer must be "sixty-three days" with a citation, with no file copied by hand.

**Effort & Granularity Check**
- **Estimate:** 6 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, backend, `deploy`
- **Granularity:** One first-run path, three defects on it.

---

### M11-FIX-DEPLOY-236 — The databases do not restart themselves when a stray process in their container dies

**Type:** Task

**User Story**
- **Actor:** anyone using Askwell.
- **User Need:** an answer that does not fail because the database restarted in the middle of it.
- **Business Value:** three times in 36 hours on the build machine, and once on the Windows test VM, Postgres reset every connection mid-work. Whatever was running failed: an eval died at task 50 of 120, and a question on the VM returned 500.

**Context / Background**
**Detailed Description:** Every occurrence logs the same line. The build machine's dev stack shows it on 2026-09-29 14:59:46, 2026-09-30 08:46:31 and 14:42:25 UTC; the Windows VM shows it on 2026-09-30 08:43:
`LOG:  untracked child process (PID …) was terminated by signal 13: Broken pipe` then `terminating any other active server processes`.
Postgres runs as PID 1 in its container, so any process that becomes orphaned there is reparented to it. That includes a `podman exec … psql` whose reader closed its pipe, and a health check. PostgreSQL 18 treats an unknown child dying on a signal as a possible crash and reinitialises. The standard fix is an init process as PID 1 (`init: true` in `compose.yaml`, Podman's `catatonit`), which reaps orphans so Postgres never sees them. Apply it to `postgres` and `sandbox`, and to any other service that runs a server as PID 1 and is exec'd into (check `redis`).

**Scope**
- `init: true` on those services in `compose.yaml`.
- A test that pins it: `compose.yaml` read as text, in the style `test_release_workflow.py` already uses.
- Find what is exec'd into the database containers and pipes into a closing reader (`scripts/dev.sh psql … | …`, health checks). Name them in the decision entry, even though `init: true` makes them harmless.

**Out of Scope**
- Postgres configuration.

**Acceptance Criteria**
- **Acceptance Criteria:**
  - The pin test passes.
  - `scripts/dev.sh check` and `test-db` pass with the stack recreated.
  - A reproduction: `podman exec askwell-postgres-1 sh -c 'yes | head -1' &` in a loop against the recreated stack leaves no `untracked child process` line in the log. Record the command and its result in the manual test.
- **Edge Cases:** the migrate service's one-shot run, unaffected. The healthcheck's exit codes, which pass through the init.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** unchanged.
- **Validation Rules:** C3: the sandbox container's restrictions are unchanged.
- **Audit / Logging Requirements:** none new.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** none.
- **API / Data Touchpoints:** `compose.yaml`.
- **Assumptions:** Podman's `init: true` (catatonit) is present on the Podman versions the installers accept (4.9 on Ubuntu 24.04, and 5.x). Verify on 4.9; if it is missing, say so.

**Effort & Granularity Check**
- **Estimate:** 2 hours · **Priority:** High
- **Labels / Component:** `phase:7`, `deploy`
- **Granularity:** One compose setting and its evidence.

---

### M11-FIX-ING-228 — A workbook's sheets ask about the columns they could not type

**Type:** Task

**User Story**
- **Actor:** anyone whose workbook has a date column like `03/04/2025`.
- **User Need:** asked once whether that is DD/MM or MM/DD, so "orders in March" is answered by date, not by text.
- **Business Value:** `docs/data-sources.md` §2 calls spreadsheets the clarification loop's best case, and for a workbook added with a folder the loop does not run.

**Context / Background**
**Detailed Description:** Read #851. `M11-FIX-ING-224` loads sheets with `raise_clarifications=False`, because `clarify.raise_candidates` and `table_infer.raise_table_inference` each skip a source that already has any clarification row, and a folder is one source. Make that guard once per document for a folder (the clarification row's evidence can carry the document), raise a workbook's table candidates within the same cap, and let `table_load.reload_source` reload one workbook's tables in a folder source by their table comment.

**Scope**
- The once-per-source guard becomes once per document for a `file` source; unchanged for `csv`/`dump`.
- A workbook's sheet candidates are raised, capped with the folder's other candidates.
- Answering a sheet's `date_format` question reloads that workbook's tables.

**Out of Scope**
- Merged headers (still skipped).

**Acceptance Criteria**
- **Acceptance Criteria:** Tests first. A folder with a PDF and a workbook asks both kinds of question. Answering a sheet's date question turns the column into `date`. `abstention.v1` does not regress.
- **Edge Cases:** a folder whose document questions were raised before this change; a workbook re-ingested after its question was answered.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** `../ux/clarifications.md` — a sheet question reads like a CSV one, naming the workbook and sheet.
- **Validation Rules:** C3 unchanged: the reload runs in the folder's sandbox database.
- **Audit / Logging Requirements:** as for CSV clarifications.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** `M11-FIX-ING-224`.
- **API / Data Touchpoints:** `askwell.clarify`, `askwell.table_infer`, `askwell.table_load.reload_source`, `askwell.reapply`.

**Effort & Granularity Check**
- **Estimate:** 5 hours · **Priority:** Medium
- **Labels / Component:** `phase:7`, `constraint:grounding`, backend

---

### M11-FIX-UI-229 — The library says when a workbook sheet was not loaded as a table, and why

**Type:** Task

**User Story**
- **Actor:** anyone whose spreadsheet question abstained.
- **User Need:** to learn that the sheet which could have answered it was not loaded, and what to change.
- **Business Value:** an abstention the user cannot explain reads as the product not working.

**Context / Background**
**Detailed Description:** Read #849. `table_load.load_workbook_tables` records `workbook_tables_loaded` (with a reason per skipped sheet) and `workbook_tables_failed` (with the cap) to the decisions store, which the library does not read. Store the outcome per workbook document where the library reads (a column or a small table, by migration). A failed load puts the folder in `attention` with the workbook, sheet and reason; a skipped sheet is a note on the document, not attention.

**Scope**
- Per-document storage of the sheet-load outcome.
- `ingest.coverage` and the library render it.

**Acceptance Criteria**
- **Acceptance Criteria:** Tests first. `docs/states-and-edge-cases.md` §3's "A workbook sheet not loaded as a table" row no longer says "Nothing today".
- **Edge Cases:** a workbook later re-ingested successfully clears the note.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** `../ux/library.md`.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** `M11-FIX-ING-224`.

**Effort & Granularity Check**
- **Estimate:** 5 hours · **Priority:** Medium
- **Labels / Component:** `phase:7`, backend, frontend

---

### M11-FIX-ING-230 — Workbooks indexed before `0.9.12` get their tables without being re-indexed

**Type:** Task

**User Story**
- **Actor:** anyone who added spreadsheets before upgrading.
- **User Need:** their spreadsheet questions answered from the sheet, as a new user's are.
- **Business Value:** without it, `M11-FIX-ING-224` helps only files added after the upgrade, and nothing tells the user to re-index.

**Context / Background**
**Detailed Description:** Read #850. Sheet tables load only when a workbook is ingested. At worker start, for each live `ready` document with `mime = filetypes.WORKBOOK_MIME` that has neither a `workbook_tables_loaded` nor a `workbook_tables_failed` decision, call `table_load.load_workbook_tables`. Idempotent, bounded by the number of workbooks, no re-embedding. The marker must not rescan a workbook whose sheets were all skipped at every start.

**Acceptance Criteria**
- **Acceptance Criteria:** Tests first. `grounded_qa.v1` run against the stack's own database (where `figures.xlsx` is a duplicate `seed_corpus` leaves alone) measures the tables.
- **Edge Cases:** the sandbox is not up at worker start (deferred, not failed); a workbook deleted between the scan and the load.
- **Permissions / Roles:** Single user — no roles.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** `M11-FIX-ING-224`.

**Effort & Granularity Check**
- **Estimate:** 3 hours · **Priority:** Medium
- **Labels / Component:** `phase:7`, backend

---

### M11-FIX-BE-231 — An answer from a workbook's sheet cites the workbook

**Type:** Task

**User Story**
- **Actor:** anyone whose spreadsheet question is answered from a sheet.
- **User Need:** see which file and which rows the number came from, and open them, as for any other answer.
- **Business Value:** since `M11-FIX-ING-224`, a sheet answer is right but uncited. That is the C4 gap: the citation is the only check the user has. In `grounded_qa.v1` each of the three headcount tasks is capped at 0.5 for the same reason.

**Context / Background**
**Detailed Description:** Read #857. A sheet is queried only after the workbook's passages abstain (`match_tables` never calls a sheet match strong). The answer then shows its query and rows, and no citation. The workbook is also a document, and its `sheet_row` chunks already anchor sheet and row. When a SQL answer's source is a folder (`DatabaseSource.kind == 'file'`), map the returned rows back to the workbook document and its sheet's row anchors, and cite those. The table comment `askwell workbook: <path>` names the document. Only cite a row that is in the result.

**Acceptance Criteria**
- **Acceptance Criteria:** Tests first. `figures-logistics-headcount`, `figures-design-headcount` and `figures-retail-headcount-paraphrase` in `grounded_qa.v1` score above 0.5, with nothing else lower. Record in `docs/BRAIN.md`.
- **Edge Cases:** an aggregate over many rows (cite the sheet, not every row); a workbook re-indexed since its tables loaded (the anchors must be current, never a retired chunk); a sheet with no document chunk left.
- **Validation Rules:** C4: never cite a row the query did not return. C7 unchanged.
- **Permissions / Roles:** Single user — no roles.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** `M11-FIX-ING-224`.

**Effort & Granularity Check**
- **Estimate:** 5 hours · **Priority:** High
- **Labels / Component:** `phase:7`, `constraint:grounding`, backend

---

### M11-FIX-TEST-232 — `grounded_qa.v1` runs to the end on a fresh database

**Type:** Task

**User Story**
- **Actor:** whoever measures a change with `grounded_qa.v1`.
- **User Need:** a before/after run on two fresh databases, with numbers that do not depend on which clarifications someone answered in the development database.
- **Business Value:** today the suite hangs on a fresh database, so every recorded number was taken on the stack's own database or a copy of it.

**Context / Background**
**Detailed Description:** Read #859. `eval/grounded.py::seed_corpus` ingests the corpus, ingestion raises a clarification, and the first question that retrieves from that source waits in `askwell.ask._await_clarification` for an answer the harness never gives. Take #859's option 1: after seeding, skip every pending clarification through `askwell.review.skip_clarification`, and record the count in the result file's metadata. `M11-FIX-ING-224` did exactly this by hand (`~/.cache/askwell-evalwt/preseed/preseed.py`) for its before and after runs.

**Acceptance Criteria**
- **Acceptance Criteria:** Tests first, for the skip after seeding. `grounded_qa.v1` finishes against a freshly migrated database with no manual step. The result file says how many clarifications were skipped.
- **Edge Cases:** a corpus that raises none; a re-run on a seeded database (`DUPLICATE`, nothing pending).
- **Validation Rules:** C5 unchanged: no abstention task changes.
- **Permissions / Roles:** Single user — no roles.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** none.

**Effort & Granularity Check**
- **Estimate:** 2 hours · **Priority:** Medium
- **Labels / Component:** `phase:7`, `eval`

---

### M11-FIX-TEST-233 — `test-db` never drops a sandbox database it did not create

**Type:** Task

**User Story**
- **Actor:** whoever runs `scripts/dev.sh test-db` on a machine with the stack up.
- **User Need:** run the tests without destroying the stack's imported tables or a running eval's.
- **Business Value:** today every `test-db` run can drop the sandbox databases behind the development database's dumps, CSVs and workbook sheets, and any eval running at the time loses its tables mid-run.

**Context / Background**
**Detailed Description:** Read #858. `api/tests/conftest_sandbox.py::_sweep` drops every idle `askwell_sbx_*` database, and the product uses the same prefix (`askwell.sandbox.PREFIX`). Take #858's option 1: test-created sandbox databases get their own prefix, and `_sweep` matches only that one.

**Acceptance Criteria**
- **Acceptance Criteria:** Tests first. A `test-db` run leaves an idle `askwell_sbx_*` database it did not create in place, and still sweeps its own leftovers.
- **Edge Cases:** a crashed earlier test run's databases (still swept); `InvalidSandboxName` still refuses any other name in product code.
- **Validation Rules:** C3 unchanged: the product's own names and roles do not change.
- **Permissions / Roles:** Single user — no roles.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** none.

**Effort & Granularity Check**
- **Estimate:** 2 hours · **Priority:** Medium
- **Labels / Component:** `phase:7`, `constraint:sandbox`

---

### M11-FIX-ING-234 — A 100,000-row CSV or sheet loads within the time cap

**Type:** Task

**User Story**
- **Actor:** anyone whose CSV or spreadsheet has a hundred thousand rows.
- **User Need:** their table loaded and queryable, as a smaller one is.
- **Business Value:** a 100k-row sheet is an ordinary spreadsheet, not an abuse case, and today it never becomes a table.

**Context / Background**
**Detailed Description:** Read #862. `askwell.table_load._insert_rows_blocking` inserts every row with its own autocommitted `INSERT`, so on the build host 100,000 rows do not finish within the default 600 s cap (`dump_import.DEFAULT_DUMP_TIME_CAP_SECONDS`) and the load is stopped with `TableCapExceeded("time")`. `M11-FIX-ING-224` made that failure bounded (the workbook still indexes as a document); this ticket makes it not happen. Take #862's option 1: insert in batches inside one transaction, and on a batch error retry that batch row by row, so `RowFailure`s keep their row numbers.

**Scope**
- Batched inserts for CSV and workbook sheets alike (one code path, `_load_table`).
- Size and time caps unchanged, checked between batches.

**Out of Scope**
- Raising either cap.

**Acceptance Criteria**
- **Acceptance Criteria:** Tests first. A 100,000-row sheet and a 100,000-row CSV load under the default caps on the build host. Every existing row-failure test passes unchanged.
- **Edge Cases:** one bad row in a batch (reported by row number, the rest of the batch loads); a batch that crosses the size cap.
- **Validation Rules:** C3 unchanged: the load runs as the sandbox owner, in the sandbox.
- **Permissions / Roles:** Single user — no roles.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** `M11-FIX-ING-224`.
- **API / Data Touchpoints:** `askwell.table_load` (`_insert_rows_blocking`).

**Effort & Granularity Check**
- **Estimate:** 3 hours · **Priority:** Medium
- **Labels / Component:** `phase:7`, `constraint:sandbox`, backend
