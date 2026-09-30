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
