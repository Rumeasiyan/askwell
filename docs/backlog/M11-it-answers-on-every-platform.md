# M11 — It answers on every platform

**Goal:** An installed Askwell answers a question on Windows and macOS, not only on Linux, and a spreadsheet question reaches the spreadsheet.

**Phase:** 7 (`../build-plan.md`) · **Depends on:** M10 · **Tickets:** 2 to start; the C5 ticket is added once the GPU experiment (`M10-FIX-DEPLOY-222` made it possible) has a result · **Estimated:** 11 hours

**Exit condition:** On the Windows test VM (`scripts/winvm.sh`, #836), a fresh install downloads the model and answers a question with a citation. `figures-logistics-headcount`, `figures-design-headcount` and `figures-retail-headcount-paraphrase` in `grounded_qa.v1` score above 0.

> **Where these came from.** The Windows test VM ran Setup end to end for the first time on 2026-09-30. After ten installer fixes (branch `fix/setup-compose-before-machine`), Askwell installs, every container runs and the window opens. It still cannot answer anything, because the inference bridge was built for Linux (#845). The spreadsheet ticket is the half of #818 that `M10-FIX-BE-220` showed is not routing (#827).

---

### M11-FIX-DEPLOY-223 — The containers reach the AI on Windows and macOS

**Type:** Task

**User Story**
- **Actor:** anyone who installs Askwell on Windows or macOS.
- **User Need:** to ask a question and get an answer.
- **Business Value:** today an installed Askwell on Windows opens, downloads its model, and then cannot answer anything. That is the whole product, on the platform most testers use.

**Context / Background**
**Detailed Description:** Read #845 first; it has the evidence and the options. Two problems. (1) `inference-bridge` listens on a Unix socket in `/run/askwell`, which is a bind mount of the host's `.run`; on Windows that path is on the Windows drive, reached through WSL's drvfs, which cannot hold a Unix socket (`OSError: [Errno 95] Operation not supported`). (2) The bridge dials `127.0.0.1` only (`UPSTREAM_HOST` in `api/src/askwell/inference/bridge.py`), but on Windows and macOS the containers run inside Podman's own Linux VM, so 127.0.0.1 is that VM, not the machine where `llama-server` runs.

The recommended design is #845's option B: on Windows and macOS only, the bridge dials the VM's host gateway (`host.containers.internal`), and the socket lives on a named volume inside the VM rather than on the host's drive. Linux keeps 127.0.0.1 and its bind mount unchanged. This changes what C1 says about the bridge, so it starts with a `docs/decisions.md` entry and the matching change to `docs/architecture.md` §5 and the bridge's docstring: the guarantee becomes "the bridge dials only this machine: 127.0.0.1 on Linux, the Podman VM's host gateway on Windows and macOS", and it must still be true by reading the code.

**Scope**
- The bridge's upstream host becomes configuration with exactly two allowed values, `127.0.0.1` and `host.containers.internal`. Any other value refuses to start.
- The socket directory can be a named volume. `compose.yaml` keeps Linux's bind mount as the default.
- The Windows and macOS installers set both in `.env`.
- `llama-server` on Windows and macOS listens where the VM can reach it. If that means an address other than 127.0.0.1, it must stay unreachable from other machines, and that is stated and tested.
- `docs/decisions.md`, `docs/architecture.md` §5 and the constraint text in `AGENTS.md` §3 C1's enforcement column are updated in the same change.

**Out of Scope**
- Running llama.cpp inside the VM (#845 option C).
- Changing any user's WSL configuration (#845 option A).
- Anything on Linux beyond keeping it unchanged.

**Acceptance Criteria**
- **Acceptance Criteria:** Unit tests: the bridge refuses any upstream but the two named; Linux's `compose.yaml` resolution is unchanged. `scripts/dev.sh test` and `test-db` pass. The Windows walkthrough (see Testing Notes) is done by a person or the orchestrating session with the VM, not by the build agent. Leave `docs/manual-tests/M11-FIX-DEPLOY-223.md` with the steps and an empty result, and do not claim it passed.
- **Edge Cases:** `llama-server` not yet running. The bridge must fail requests with a clear error, not crash-loop. A second Windows machine on the same network must not reach the llama-server port.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** unchanged; the existing inference-unreachable states apply.
- **Validation Rules:** C1: no address that leaves this machine. C8: nothing secret in `.env.example` beyond placeholders.
- **Audit / Logging Requirements:** the bridge logs its upstream host at start.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** `fix/setup-compose-before-machine` merged (the Windows installer fixes), `M10-FIX-DEPLOY-222`.
- **API / Data Touchpoints:** `api/src/askwell/inference/bridge.py`, `api/src/askwell/inference/client.py`, `compose.yaml`, `deploy/windows/install.ps1`, `deploy/windows/lib.ps1`, `deploy/macos/install.sh`, `deploy/inference/askwell-inference`.
- **Assumptions:** `host.containers.internal` resolves inside Podman machine containers on Windows (WSL) and macOS. **Verify it on the Windows VM before building on it**; if it does not resolve, say so and stop.

**Testing Notes / Scenarios**
- **Windows walkthrough (not the agent's):** `scripts/winvm.sh reset && scripts/winvm.sh start`, then install a Setup built from this branch, download the model from the setup screen, and ask "What is the notice period in handbook A?" with `eval/fixtures/corpus` added.
- **Known gaps:** macOS is unverified on hardware (#592); say so in the manual test.

**Effort & Granularity Check**
- **Estimate:** 6 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, `deploy`, `constraint:local-first`
- **Granularity:** One transport change behind one decision.

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
