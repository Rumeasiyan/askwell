# M10 — It is ready for 1.0

**Goal:** Close the gap between the `0.9.0` beta and a `1.0.0` that passes its own release checklist in full.

**Phase:** 7 (`../build-plan.md`) · **Depends on:** M9 · **Tickets:** 3 to start; the C5 ticket is added once the GPU experiment has a result · **Estimated:** 13 hours

**Exit condition:** Document and spreadsheet questions each reach the path that can answer them. CI compiles the desktop shell on every push. `grounded_qa.v1` meets its 0.85 bar.

> **Where these came from.** `0.9.0` shipped as a beta because two measures fail (`release-log.md`, 0.9.0). These tickets are the parts of that gap that need no product decision. Abstention (#769, #814) waits on an experiment: the host's `llama.cpp` is a CPU-only build, and whether the 9B model on its GPU clears the 0.90 bar decides what the C5 ticket should be.

---

### M10-FIX-BE-220 — Each question reaches the path that can answer it

**Type:** Task

**User Story**
- **Actor:** anyone with both documents and a spreadsheet added.
- **User Need:** a document question answered from the document, and a spreadsheet question from the spreadsheet.
- **Business Value:** today 8 of the 40 `grounded_qa.v1` tasks fail on routing alone, and the user sees either a SQL refusal or "I don't know" for something that is in their files.

**Context / Background**
**Detailed Description:** Two defects, one decision point. Document questions are sent to SQL generation, which returns prose instead of a query. `sqlglot` refuses it (C2, correctly), and the refusal is shown as the answer (#817). Spreadsheet questions go down the document path and abstain (#818). Both issues hold the evidence and the task ids. Take the SQL path only when the question plausibly concerns a table: its terms match a table name, a column name or a schema note. When generation yields no valid query, fall back to document retrieval instead of returning the refusal. When the document path finds nothing and a table plausibly matches, try the table.

**Scope**
- One routing decision, with a fallback in each direction.
- The SQL refusal is never the user-facing answer when a document could answer.

**Out of Scope**
- Changing C2. Every generated query is still parsed with `sqlglot` and refused unless it is a single `SELECT`/`WITH`.

**Acceptance Criteria**
- **Acceptance Criteria:** The 8 tasks named in #817 and #818 pass. `grounded_qa.v1` is re-run on this machine with nothing else using `llama-server` and recorded in `../BRAIN.md` — honestly, whatever it shows.
- **Edge Cases:** A question that genuinely needs both a document and a table — the tool loop's job, unchanged. No database sources at all — the SQL path is never tried.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** `../ux/ask.md` §5.
- **Validation Rules:** C2 is untouched. Do not lower any threshold or pass bar. **Run evals one at a time: two runs sharing one `llama-server` time out and corrupt both** (`../BRAIN.md` Eval baseline).
- **Audit / Logging Requirements:** The route taken is visible in the trace.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** M4-SQL-BE-108a, M4-CSV-ING-094, M5-LOOP-BE-115.
- **API / Data Touchpoints:** `api/src/askwell/ask.py` routing; `api/src/askwell/agent/sql_generate.py`.
- **Assumptions:** Table and column names are available cheaply at routing time. If they are not, say so.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** With `eval/fixtures/corpus` added, ask "What is the battery life in the spec?" and "What is the logistics headcount?" and confirm each is answered from its own source.
- **Known gaps:** Close #817 and #818 with the recorded numbers.

**Effort & Granularity Check**
- **Estimate:** 6 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, `constraint:grounding`, `constraint:sql-safety`, backend
- **Granularity:** One routing decision and two fallbacks.

---

### M10-TEST-DEPLOY-221 — CI compiles the desktop shell on every push that touches it

**Type:** Task

**User Story**
- **Actor:** whoever next changes the desktop shell.
- **User Need:** to find out in minutes, not at release time, that it does not compile.
- **Business Value:** the shell's first compile was the `0.9.0` release build, and it failed three ways, one 45-minute build at a time (#821).

**Context / Background**
**Detailed Description:** Issue #821 has the full account. Add a Linux CI job that runs `cargo check` in `web/src-tauri` on any push touching it, with the Tauri system libraries installed. The list the fix needed is already in #822's history and in `.github/workflows/release.yml`. Add a test that fails if the command list in `build.rs` and `generate_handler!` in `main.rs` ever differ, since that mismatch was the first of the three failures.

**Scope**
- A `cargo check` job in `.github/workflows/ci.yml`, path-filtered to `web/src-tauri/**`.
- A check that `build.rs`'s command list equals `main.rs`'s registered handlers.

**Out of Scope**
- Building installers on every push (`release.yml` does that).

**Acceptance Criteria**
- **Acceptance Criteria:** A push that touches the shell runs the job, and it passes on current `main`. Removing a command from `build.rs` while keeping it in `main.rs` makes the job fail — proved on a throwaway branch, not assumed.
- **Edge Cases:** A push touching nothing in the shell — the job does not run.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** None.
- **Validation Rules:** No secret in CI (C8).
- **Audit / Logging Requirements:** None.
- **Analytics Events:** None.

**Dependencies & Assumptions**
- **Dependencies:** M7-TAURI-DEPLOY-181, M9-REL-DEPLOY-214.
- **API / Data Touchpoints:** `.github/workflows/ci.yml`; `web/src-tauri/build.rs`, `web/src-tauri/src/main.rs`.
- **Assumptions:** A cold `cargo check` fits comfortably in a CI job. Cache `~/.cargo` and `target/` if it does not.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Open a PR that touches `build.rs` and watch the job run.
- **Known gaps:** Close #821.

**Effort & Granularity Check**
- **Estimate:** 3 hours · **Priority:** High
- **Labels / Component:** `phase:7`, deploy, test
- **Granularity:** One job and one consistency check.

---

### M10-FIX-DEPLOY-222 — A machine with a GPU gets a GPU build of llama.cpp

**Type:** Task

**User Story**
- **Actor:** someone whose laptop has a graphics card.
- **User Need:** answers at the speed their hardware allows.
- **Business Value:** the build host has an 8 GB RTX 3050, and its hardware probe reports the `accelerated` profile. Yet every answer ran on CPU for the whole build, because the `llama.cpp` it runs has no GPU backend. An installed copy would behave the same way.

**Context / Background**
**Detailed Description:** `~/.local/opt/llama.cpp` holds only `libggml-cpu-*` backends — no CUDA, no Vulkan. `deploy/inference/askwell-inference` already detects GPU offload from `llama-server`'s log (`_detect_acceleration`) and reports `cpu` because none happens. Find out which `llama.cpp` the installers (`M7-PACK-DEPLOY-139`/`140`/`141`) put on a user's machine, and make a machine with a supported GPU get a build with a GPU backend and `--n-gpu-layers` set. Keep the CPU build for machines without one. Vulkan covers NVIDIA, AMD and Intel with one prebuilt binary on Linux and Windows, and Metal is built in on Apple silicon. Prefer that over a per-vendor CUDA build unless measurement shows a reason not to.

**Scope**
- The installers choose a GPU-capable `llama.cpp` when the probe finds a supported GPU.
- `askwell-inference` passes `--n-gpu-layers` on those machines.
- The CPU path unchanged for everyone else.

**Out of Scope**
- Choosing a bigger model. That is the C5 work, after this lands and is measured.

**Acceptance Criteria**
- **Acceptance Criteria:** On a machine with a supported GPU, `/health` reports `acceleration: gpu`, and a grounded question is measurably faster than on CPU — both numbers recorded. On a machine without one, nothing changes.
- **Edge Cases:** GPU present but the driver is too old for the backend — falls back to CPU, and the reason is stated. A GPU with too little memory — partial offload rather than failure.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** Settings' hardware profile shows the real acceleration.
- **Validation Rules:** C1: the binary is bundled or placed at install time, never fetched at runtime. C9: the `llama.cpp` build's licence is MIT, re-verified.
- **Audit / Logging Requirements:** None.
- **Analytics Events:** None.

**Dependencies & Assumptions**
- **Dependencies:** M7-PACK-DEPLOY-139, M7-PACK-DEPLOY-140, M7-PACK-DEPLOY-141, M7-OFFLINE-DEPLOY-144.
- **API / Data Touchpoints:** `deploy/inference/askwell-inference`; `deploy/*/install.*`; `.github/workflows/release.yml`.
- **Assumptions:** Vulkan works with the NVIDIA 580 driver on this host. If it does not, say so rather than switching to CUDA silently.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** On the build host, confirm `/health` reports `gpu`, then time one question against the CPU figure.
- **Known gaps:** Real Windows and macOS GPUs are untested (#590, #592).

**Effort & Granularity Check**
- **Estimate:** 4 hours · **Priority:** High
- **Labels / Component:** `phase:7`, deploy, `constraint:local-first`
- **Granularity:** One backend choice at install time and one flag.

---
