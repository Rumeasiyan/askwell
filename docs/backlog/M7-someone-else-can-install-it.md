# M7 — Someone else can install it

**Goal:** A clean machine installs Askwell and runs it with the network cable unplugged; a backup taken on one machine restores onto another with corpus and memory intact; and everything unglamorous that a release actually needs exists.

**Phase:** 6 (`../build-plan.md`) · **Depends on:** M6 · **Tickets:** 32 · **Estimated:** 97–141 hours of unblocked work

**Exit condition:** A non-technical person installs Askwell on Linux, Windows or macOS, is given a profile with what to expect, reaches a first cited answer, and can do all of it disconnected from the internet. A backup restores onto a clean machine with a tested procedure. The log budget degrades in the right order. The licence and notices file, the support boundary and the release checklist all exist before anything is published.

> **Discovering this work a week before release is how releases slip.** None of it is in the business case and all of it is required to ship.

## Included epics

| Epic | Code | Covers |
| ---- | ---- | ------ |
| Hardware probe | `PROBE` | Host-side detection, profile, warn-and-continue |
| Packaging | `PACK` | Three installers, supervision of stack plus native process |
| Offline install | `OFFLINE` | Bundled models, manual placement, the cable-unplugged test |
| Settings | `SET` | The six sections completed |
| Security | `SEC` | Passphrase, encryption at rest, security review |
| Logs | `LOG` | Budget, retention, export, verification |
| Backup | `BACKUP` | Backup, restore, tested restore |
| Data ownership | `DATA` | Export everything, delete, reset |
| Update delivery | `UPDATE` | **Blocked on an open decision** |
| Release readiness | `QA`, `DOC`, `OPS`, `PERF` | Checklist, licence and notices, support boundary, rollback, performance |

---

### M7-PROBE-DEPLOY-137 — Host-side hardware probe and profile selection

**Type:** Story

**User Story**
- **Actor:** someone installing on a machine whose specification they could not state.
- **User Need:** Askwell to work out what their machine can do and pick sensible defaults.
- **Business Value:** a wrong profile is worse than a missing one, and a container sees the cgroup's or the virtual machine's view of memory rather than the machine's.
- *As someone who does not know how much video memory my laptop has, I want Askwell to work it out, so that I get a model that actually runs.*

**Context / Background**
**Detailed Description:** The probe runs on the host at install time, not inside a container, and reports memory, processor, accelerator and free disk. It selects one of the four profiles and records the selection with the evidence. Where detection fails, it defaults to the standard profile and says so.

**Scope**
- Host-side probe on all three platforms reporting the four measures.
- Profile selection with the four documented thresholds.
- Recording the selection and its evidence, and re-running on demand from settings.
- Fallback to standard with an explicit statement when detection fails.

**Out of Scope**
- The warn-and-continue interface (M7-PROBE-FE-138).
- Model download, which is the first-run sequence.

**Acceptance Criteria**
- **Acceptance Criteria:** The probe runs on the host and reports real machine values, not a container's view. A profile is selected according to the documented thresholds. Failed detection falls back to standard with a stated reason. The selection and its evidence are recorded.
- **Edge Cases:** A machine with an accelerator the probe does not recognise — treated as absent, stated, and the user can override the profile. A virtual machine reporting the host's memory dishonestly — the value is used and the source is stated. Disk free changing between probe and install — rechecked before the model step.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/first-run.md` §2 step 2; `../ux/settings.md` §2.
- **Validation Rules:** The probe never runs inside a container.
- **Audit / Logging Requirements:** Profile selection is a decisions record with the evidence.
- **Analytics Events:** Local only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user on a machine with 16 GB and no accelerator is told to expect answers in about fifteen seconds and that voice will work.

**Dependencies & Assumptions**
- **Dependencies:** M0-MODEL-DEPLOY-018.
- **API / Data Touchpoints:** `settings`; profile configuration.
- **Assumptions:** Concurrency is not a dimension of the profile — one user asks one question at a time.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Install on a clean machine and observe the probe running before any container starts. Read the reported values and compare them with the machine's real specification. Confirm the selected profile matches the thresholds. Re-run the probe from settings and confirm the same result.
- **Other scenarios:** Disable accelerator detection and confirm the fallback with its stated reason.
- **Known gaps:** Accelerator detection coverage varies; unknown devices are treated as absent.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:6`, deployment
- **Granularity:** One probe across three platforms. Upper bound.

---

### M7-PROBE-FE-138 — Warn and continue below the floor, and when the probe fails

**Type:** Story

**User Story**
- **Actor:** someone on an older machine below the minimum.
- **User Need:** to be warned honestly and allowed to try.
- **Business Value:** refusing made sense for a paid deployment that could be blamed on the vendor; for a free download it is just a lost user.
- *As someone with an old laptop, I want to be told it will be slow and allowed to try anyway, so that I can decide for myself.*

**Context / Background**
**Detailed Description:** Below the light floor, warn clearly with what to expect and allow continuing. When the probe fails, say so, use the standard profile, and allow continuing. In both cases the profile can be changed later in settings. Never refuse to run.

**Scope**
- Below-floor warning with concrete expectations.
- Probe-failure statement with the fallback named.
- Profile override in settings with the consequences stated.

**Out of Scope**
- Blocking installation for any hardware reason.

**Acceptance Criteria**
- **Acceptance Criteria:** Below-floor hardware produces a warning naming what will be slow, and installation continues. A failed probe states the fallback and continues. The profile can be changed afterwards. Nothing refuses to run on hardware grounds.
- **Edge Cases:** Hardware so limited that the smallest model cannot load — the warning says the assistant may not start, and document indexing and search still work, which is an honest partial product rather than a refusal. Overriding to a profile the machine cannot support — permitted with the consequence stated, and the assistant reports its failure clearly if it cannot load.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/first-run.md` §4 below hardware floor; `../states-and-edge-cases.md` §6 hardware below the floor — **warn, do not refuse**.
- **Validation Rules:** No hardware condition may block installation.
- **Audit / Logging Requirements:** The warning and the user's choice are decisions records.
- **Analytics Events:** Local only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user with 6 GB is warned, continues, finds indexing works and answers are slow, and decides it is still useful.

**Dependencies & Assumptions**
- **Dependencies:** M7-PROBE-DEPLOY-137, M1-LIB-FE-052.
- **API / Data Touchpoints:** `settings`.
- **Assumptions:** An honest warning is more useful than a refusal, and a user who continues and finds it slow was better served than one turned away.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Install on a machine below the floor, or constrain the probe's reported memory. Read the warning and confirm it names what will be slow. Continue and confirm the install completes and documents index. Open settings and change the profile, confirming the consequence is stated.
- **Other scenarios:** Force a probe failure and confirm the standard fallback is stated rather than silent.
- **Known gaps:** No prediction of how slow — only qualitative expectations.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:6`, frontend, deployment
- **Granularity:** Two warnings and one override.

---

### M7-PACK-DEPLOY-139 — Linux installer

**Type:** Story

**User Story**
- **Actor:** a Linux user who has never used containers.
- **User Need:** one installation that sets up everything.
- **Business Value:** every container is something a non-technical user must have working unaided.
- *As someone who wants to try this without learning container tooling, I want one installer, so that installation is not a systems task.*

**Context / Background**
**Detailed Description:** A Linux installer that checks for or installs the container runtime, places the container images and the native inference binary, runs the probe, creates the data directories, registers the service so it starts with the session, and opens the browser at the local address. It never fetches a model at runtime; models come from the bundle or manual placement.

**Scope**
- Runtime check and guidance, image placement, native binary placement.
- Data directory creation with sensible defaults and a way to choose another location.
- Session start registration and first launch.
- Clean uninstall that removes Askwell's data only on explicit request and never touches the user's own files.

**Out of Scope**
- Windows and macOS (their own tickets).
- Update delivery — blocked.

**Acceptance Criteria**
- **Acceptance Criteria:** A clean Linux machine installs and reaches the first-run screen. The container runtime is present or the installer says exactly what to install. Data directories are created and their location is shown. Uninstall removes Askwell without touching indexed files.
- **Edge Cases:** A machine with an incompatible runtime version — named, with the required version. Insufficient disk — refused before copying, naming the space needed. A previous installation present — upgraded in place or reported, never silently overwriting data. Installation without administrative rights — supported where possible and clearly refused with the reason where not.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/first-run.md` §2.
- **Validation Rules:** The installer never fetches a model.
- **Audit / Logging Requirements:** Installation writes an install record; the audit stores begin at first launch.
- **Analytics Events:** None — the installer transmits nothing.

**Real-World Example Scenarios**
- A researcher installs on their laptop in five minutes and lands on the first-run screen without opening a terminal.

**Dependencies & Assumptions**
- **Dependencies:** M7-PROBE-DEPLOY-137, M0-STACK-DEPLOY-009, M0-MODEL-DEPLOY-018.
- **API / Data Touchpoints:** File system; container runtime.
- **Assumptions:** Podman is the supported runtime and no Docker daemon is assumed anywhere.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** On a clean Linux virtual machine with no container tooling, run the installer. Follow whatever it says about the runtime. Watch it place images, run the probe and start. Confirm the browser opens on the first-run screen. Reboot and confirm Askwell starts with the session. Then uninstall and confirm the indexed files on disk are untouched.
- **Other scenarios:** Install over an existing installation and confirm data survives.
- **Known gaps:** No update mechanism — blocked. Distribution coverage is limited to the tested set and is stated.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:6`, deployment
- **Granularity:** One platform end to end. Upper bound.

---

### M7-PACK-DEPLOY-140 — Windows installer

**Type:** Story

**User Story**
- **Actor:** a Windows user, which is most of the target audience by numbers.
- **User Need:** a normal Windows installation experience.
- **Business Value:** the platform decision was made precisely so this audience is not excluded.
- *As someone on a work-issued Windows laptop, I want a normal installer, so that I can try this without administrator help if possible.*

**Context / Background**
**Detailed Description:** A Windows installer covering the same ground as the Linux one, with the platform's particular problems handled: the container runtime's virtualisation requirements, antivirus interference with the native inference binary, path length limits, and file paths for registered roots that cross the virtual machine boundary.

**Scope**
- Installation with runtime prerequisites checked and explained.
- Native binary placement with guidance if antivirus quarantines it.
- Registered-root path handling across the virtualisation boundary.
- Start with the session, and uninstall.

**Out of Scope**
- Enterprise deployment tooling.

**Acceptance Criteria**
- **Acceptance Criteria:** A clean Windows machine installs and reaches the first-run screen. Virtualisation prerequisites are checked and explained where missing. A quarantined inference binary produces a message naming the file and the likely cause. Registered roots on Windows paths work for indexing and for the source viewer.
- **Edge Cases:** Virtualisation disabled in firmware — named, with what to enable, since it is not something Askwell can fix. A user without administrator rights — supported where possible, refused clearly where not. A path exceeding the platform's length limit — reported per file rather than failing the batch. A drive letter that changes between sessions — the root reports unavailable rather than every document reporting missing.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/first-run.md` §2; `../ux/source-viewer.md` §4 for the unavailable-root case.
- **Validation Rules:** No model is fetched.
- **Audit / Logging Requirements:** As the Linux installer.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A lawyer installs on their firm laptop, hits a quarantined binary, reads the message, releases it from quarantine, and continues.

**Dependencies & Assumptions**
- **Dependencies:** M7-PACK-DEPLOY-139, M1-ADD-ING-021.
- **API / Data Touchpoints:** File system; container runtime; registered roots.
- **Assumptions:** The virtualisation layer is the main source of platform-specific failure and most of the work is in explaining it well.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** On a clean Windows virtual machine, run the installer with virtualisation initially disabled — confirm the message names what to enable. Enable it and install. Reach the first-run screen. Nominate a folder on a normal Windows path, add a PDF, ask a question, and click a citation to confirm the viewer opens the file across the boundary. Restart the machine and confirm Askwell starts.
- **Other scenarios:** Change a drive letter and confirm the root reports unavailable rather than mass file-missing.
- **Known gaps:** Enterprise-managed machines with restrictive policies may not install, and the documentation says so.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:6`, deployment
- **Granularity:** One platform end to end. Upper bound.

---

### M7-PACK-DEPLOY-141 — macOS installer

**Type:** Story

**User Story**
- **Actor:** a consultant on a Mac, which is what most of this audience carries.
- **User Need:** acceleration actually used on their hardware.
- **Business Value:** native inference exists precisely so the accelerated profiles are reachable here.
- *As someone on a Mac laptop, I want Askwell to use my machine properly, so that answers are fast rather than the platform being an afterthought.*

**Context / Background**
**Detailed Description:** A macOS installer covering the same ground, with the platform's particular problems: code signing and notarisation of the native binary, the security prompt on first run, permission to read the nominated folders, and mounting those folders into the container runtime's virtual machine.

**Scope**
- Signed and notarised native binary with the first-run prompt handled gracefully.
- Folder access permission requests at root registration time, explained.
- Root mounting into the runtime's virtual machine.
- Start with the session, and uninstall.

**Out of Scope**
- Distribution through an app store.

**Acceptance Criteria**
- **Acceptance Criteria:** A clean Mac installs and reaches the first-run screen. The native binary runs without the user disabling security features. Nominating a folder prompts for permission with an explanation and then works, including in the source viewer. Acceleration is detected and used on capable hardware.
- **Edge Cases:** Permission denied for a nominated folder — reported as a permission problem with how to grant it, not as a missing file. A folder outside the permitted areas — the prompt explains and the registration is refused with the reason. An accelerator present but unusable because of a driver or runtime issue — reported and the profile falls back with a statement.
- **Permissions / Roles:** Single user — no roles in the product. Operating-system folder permissions are the subject here.
- **UI States:** `../ux/first-run.md` §2; `../ux/add-source.md` for root registration.
- **Validation Rules:** No model is fetched.
- **Audit / Logging Requirements:** As the Linux installer.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A consultant installs, grants access to their client folder, and gets answers in three seconds because the accelerator is used.

**Dependencies & Assumptions**
- **Dependencies:** M7-PACK-DEPLOY-140, M1-ADD-ING-021.
- **API / Data Touchpoints:** File system permissions; container runtime; the native process.
- **Assumptions:** Signing and notarisation are required for a credible install and the certificate is available; if it is not, that becomes a blocking issue to raise rather than a workaround to ship.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** On a clean Mac, run the installer. Confirm the security prompt is a normal one and that no security feature must be disabled. Reach first run. Nominate a folder in your documents, read the permission explanation, grant it, add a PDF and ask a question. Click a citation and confirm the viewer opens it. Check settings and confirm the profile reports acceleration in use.
- **Other scenarios:** Deny folder permission and confirm the message names permission rather than a missing file.
- **Known gaps:** No app store distribution. Older hardware without acceleration falls back and says so.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:6`, deployment
- **Granularity:** One platform end to end. Upper bound.

---

### M7-PACK-DEPLOY-142 — Supervise the container stack and the native process together

**Type:** Story

**User Story**
- **Actor:** someone whose Askwell did not come back after a restart.
- **User Need:** both halves started, watched and restarted as one thing.
- **Business Value:** the accepted cost of native inference is an installer managing a process alongside a container stack; leaving that unmanaged turns the cost into a support queue.
- *As someone who just wants to open Askwell, I want everything it needs started for me, so that I never think about processes and containers.*

**Context / Background**
**Detailed Description:** The installer provisions and supervises both the container stack and the native inference process, starting them in the right order, restarting either on failure with backoff, and reporting the two causes of unavailability separately. Stopping Askwell stops both.

**Scope**
- Supervision of both halves on all three platforms.
- Ordered start, backoff restart, and clean stop.
- State reported to the supervision surface and the health endpoint.

**Out of Scope**
- The supervision interface (M7-PACK-FE-143).

**Acceptance Criteria**
- **Acceptance Criteria:** Starting Askwell starts the stack and the native process in order. Killing either results in a supervised restart. Stopping Askwell stops both, leaving nothing running. The two failure causes are reported separately.
- **Edge Cases:** The machine sleeping and waking — both halves recover without user action. A restart loop — backoff caps and the state becomes failed with the last reason, rather than restarting forever. A user starting Askwell twice — the second start attaches rather than creating a duplicate stack.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../states-and-edge-cases.md` §1 model not loaded; M0-MODEL-BE-020's two causes.
- **Validation Rules:** Stopping must leave no orphaned container or process.
- **Audit / Logging Requirements:** Supervision events are logged with cause.
- **Analytics Events:** Local only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user closes the lid for three days, opens it, and Askwell answers a question a few seconds later without them doing anything.

**Dependencies & Assumptions**
- **Dependencies:** M7-PACK-DEPLOY-141, M0-MODEL-DEPLOY-018.
- **API / Data Touchpoints:** Health surface.
- **Assumptions:** Each platform's own service mechanism is used rather than a custom supervisor.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** On each platform, start Askwell from the desktop entry point and confirm both halves come up. Kill the inference process and watch it restart. Kill a container and watch the same. Stop Askwell and confirm nothing remains running. Sleep the machine, wake it, and confirm a question works without intervention.
- **Other scenarios:** Induce a restart loop and confirm backoff caps with a failed state.
- **Known gaps:** Recovery from a corrupted container volume is not automatic; the repair path is manual and documented.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:6`, deployment
- **Granularity:** One supervision model across three platforms. Upper bound.

---

### M7-PACK-FE-143 — A supervision surface: start, stop, repair, and what is wrong

**Type:** Story

**User Story**
- **Actor:** someone whose Askwell says the assistant is unavailable.
- **User Need:** a button rather than a set of instructions.
- **Business Value:** describing a fix is better than nothing; performing it is what a non-technical user actually needs.
- *As someone who is not going to open a terminal, I want a restart button, so that the fix I was told about is something I can do.*

**Context / Background**
**Detailed Description:** A small surface — reachable from the desktop entry point and from the unavailable state in the application — showing the state of the stack and the native process, with start, stop and restart actions and the last failure reason for each. It works even when the API is down, because that is exactly when it is needed.

**Scope**
- State display for both halves with the last failure reason.
- Start, stop and restart actions for each and for both.
- Availability when the API is not running.
- A path to the log files for a bug report.

**Out of Scope**
- Diagnosing container-runtime problems beyond reporting them.

**Acceptance Criteria**
- **Acceptance Criteria:** The surface shows both halves with their state and last failure reason. Actions work. It is reachable and functional when the API is down. It offers the log location for a bug report.
- **Edge Cases:** The container runtime itself not running — reported with what to start, since Askwell cannot start it. Both halves healthy — the surface says so plainly rather than inviting unnecessary action. A restart that fails — the reason is shown rather than the action silently doing nothing.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §5 model unavailable links here; `../states-and-edge-cases.md` §1.
- **Validation Rules:** The surface must not depend on the API being up.
- **Audit / Logging Requirements:** Manual start and stop are logged.
- **Analytics Events:** Local only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user sees the assistant is unavailable, clicks through to the supervision surface, presses restart, and is answering questions a minute later.

**Dependencies & Assumptions**
- **Dependencies:** M7-PACK-DEPLOY-142, M0-MODEL-BE-020.
- **API / Data Touchpoints:** Supervision state; log paths.
- **Assumptions:** A minimal native surface is needed because a browser-served one cannot be shown when the API is down.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** With Askwell running, stop the API container from outside. Open the supervision surface from the desktop entry point and confirm it loads and reports the API as down with a reason. Press restart and watch it recover, then open the browser and confirm the product works. Repeat with the inference process.
- **Other scenarios:** Stop the container runtime entirely and confirm the surface says what to start.
- **Known gaps:** It reports runtime problems rather than fixing them.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:6`, deployment, frontend
- **Granularity:** One surface with three actions.

---

### M7-OFFLINE-DEPLOY-144 — Offline model bundle and manual model placement

**Type:** Story

**User Story**
- **Actor:** someone on an air-gapped machine, who is the user this product exists for most.
- **User Need:** to install and run with no network at all.
- **Business Value:** the offline user is a core case and cannot be an afterthought.
- *As someone whose work machine has never been on the internet, I want to install Askwell from a file, so that the product I chose for privacy does not require connectivity to set up.*

**Context / Background**
**Detailed Description:** Two paths: an install bundle containing the models for a chosen profile, and a manual placement path where the user puts a model file in a named location and Askwell finds it. The settings screen names the expected file and location when a model is missing. Model files are never fetched at runtime under any circumstances.

**Scope**
- Bundle format containing images, the native binary and the profile's models.
- Manual placement path with the expected filename and location stated.
- Model discovery and validation on start, including a checksum so a corrupt file is named rather than crashing.
- The first-run download step offering the manual path when the download fails.

**Out of Scope**
- Distributing the bundle — that is a release-process concern.

**Acceptance Criteria**
- **Acceptance Criteria:** The bundle installs and runs a complete Askwell with no network access at any point. A manually placed model file is discovered and validated. A corrupt model is named rather than causing an obscure failure. Settings names the expected file and location when a model is missing.
- **Edge Cases:** A model for the wrong profile placed manually — accepted with the profile adjusted and stated, rather than refused. Several models present — the configured one is used and the others are listed as available for swapping. A partially copied file — checksum failure names it.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/first-run.md` §4 download failed and §6; `../ux/settings.md` §8 model file missing.
- **Validation Rules:** No runtime model download, ever.
- **Audit / Logging Requirements:** Model discovery and validation are logged; a model swap is a decisions record.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A user copies the bundle onto a USB drive, installs on an air-gapped machine, and asks their first question without the machine ever having a network route.

**Dependencies & Assumptions**
- **Dependencies:** M7-PACK-DEPLOY-142.
- **API / Data Touchpoints:** Model directory; `settings`.
- **Assumptions:** Bundle size for one profile is acceptable on removable media; larger profiles are separate bundles.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** On a machine with the network interface disabled, install from the bundle. Complete first run, add a document, and ask a question that returns a cited answer. At no point should anything report a network failure, because nothing should have tried. Then remove the model file, restart, and read the settings message naming the expected file and location. Place it manually and confirm recovery.
- **Other scenarios:** Truncate a model file and confirm the checksum failure names it.
- **Known gaps:** Bundles are per profile, so a user changing profile may need another file.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:6`, deployment, `constraint:local-first`
- **Granularity:** Bundle plus manual path plus validation. Upper bound.

---

### M7-OFFLINE-TEST-145 — The cable-unplugged release test

**Type:** Story

**User Story**
- **Actor:** the maintainer about to publish a release.
- **User Need:** the local-only claim verified rather than asserted, every release.
- **Business Value:** the promise is verified as part of every release, not asserted, and the tracked figure is zero network calls in local mode.
- *As someone whose product's entire claim is that nothing leaves the machine, I want that tested before every release, so that the claim stays true rather than becoming folklore.*

**Context / Background**
**Detailed Description:** A documented and partly automated release test: install on a clean machine, disconnect the network entirely, and exercise the whole product — first run with a manually placed model, add every source kind, ask, abstain, clarify, correct, query a database, use voice, take a backup. Simultaneously observe the egress proxy's counters and an external network capture. The pass condition is zero outbound requests.

**Scope**
- The documented test procedure covering every feature.
- Proxy counter verification and an independent network capture.
- A pass or fail recorded per release with the evidence.
- Automation of the parts that can be automated, with the manual walkthrough retained.

**Out of Scope**
- Online AI mode, which is deliberately excluded and tested separately in M8.

**Acceptance Criteria**
- **Acceptance Criteria:** The full feature walkthrough completes with the network disconnected. The proxy reports zero permitted outbound requests. The independent capture shows no traffic leaving. Any refusal counted by the proxy is investigated and named, not dismissed. The result is recorded for the release.
- **Edge Cases:** A refusal counted for a benign dependency check — investigated and the dependency fixed or documented, never accepted as noise. A live database connection configured — excluded from this test, or included with its single permitted destination and counted separately. A font or asset request in the built frontend — a release blocker.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../states-and-edge-cases.md` §1 — **never render an offline warning**, which this test also verifies.
- **Validation Rules:** Zero permitted outbound requests. Refusals must be zero or explained.
- **Audit / Logging Requirements:** The test result is recorded with the release.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A dependency upgrade adds a version check on import; the release test catches it before anyone installs it.

**Dependencies & Assumptions**
- **Dependencies:** M7-OFFLINE-DEPLOY-144, M0-STACK-SEC-011, M6-VUI-FE-135.
- **API / Data Touchpoints:** Proxy counters; external capture.
- **Assumptions:** An external capture is necessary because a counter produced by the system under test is not sufficient evidence on its own.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** This ticket is itself a manual walkthrough. On a clean machine with a network capture running on another host or at the interface, install from the offline bundle, physically disconnect, and work through the entire product: first run, add files, add a CSV, import a dump, ask, abstain, answer a clarification, correct a fact, use voice, take a backup, export the log. Confirm nothing failed for network reasons, no offline banner appeared anywhere, and both the proxy counter and the capture show nothing left the machine.
- **Other scenarios:** Repeat with the network connected but the proxy denying, and confirm identical behaviour.
- **Known gaps:** The test is manual in large part and takes a working session; automating more of it is a follow-up.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:6`, test, security, `constraint:local-first`
- **Granularity:** One procedure with two independent verifications. Upper bound.

---

### M7-SET-FE-146 — Settings: model and speed

**Type:** Story

**User Story**
- **Actor:** someone wondering why answers take fifteen seconds.
- **User Need:** to see their profile, their model and real numbers.
- **Business Value:** real numbers rather than a rating is what lets someone decide whether to change something.
- *As someone deciding whether to try a bigger model, I want the real throughput and memory numbers, so that I can judge rather than guess.*

**Context / Background**
**Detailed Description:** The first settings section: current profile with what it means in plain terms, the model in use with a swap control, memory footprint and measured throughput as real numbers, and the retrieval threshold with the same warning as the trace panel. Swapping makes the assistant briefly unavailable, retrieval keeps working, and that is stated.

**Scope**
- Profile display with expectations and a re-probe action.
- Model display and swap, with the unavailability stated before it happens.
- Measured memory and throughput.
- Threshold control with the consequence, identical to the trace panel's.

**Out of Scope**
- Model download — models are bundled or placed manually.

**Acceptance Criteria**
- **Acceptance Criteria:** The section shows the profile with what to expect, the model in use, real memory and throughput figures, and the threshold with its warning. Swapping a model states the brief unavailability first, and retrieval keeps working during it.
- **Edge Cases:** No alternative model present — swap says so and names where to place one. A swap that fails — the previous model is restored and the failure is named. Throughput unmeasured because no question has been asked — states that rather than showing zero.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §2 and §8 model swapping and model file missing; `../states-and-edge-cases.md` §6.
- **Validation Rules:** The threshold control is never a frictionless slider.
- **Audit / Logging Requirements:** Model swap and threshold change are decisions records.
- **Analytics Events:** Local counters only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user sees fourteen tokens per second, places a smaller model, swaps to it, and finds answers acceptable at twice the speed.

**Dependencies & Assumptions**
- **Dependencies:** M7-PROBE-FE-138, M5-TRACE-FE-122, M7-OFFLINE-DEPLOY-144.
- **API / Data Touchpoints:** `settings`; the inference client.
- **Assumptions:** Throughput can be measured from real turns rather than a synthetic benchmark.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask two questions, then open settings. Read the profile, the model, the memory footprint and the throughput, and confirm the numbers are plausible against what you just experienced. Place a second model file, swap to it, and confirm the stated brief unavailability, that browsing and search still work during it, and that the new model is in use afterwards.
- **Other scenarios:** Adjust the threshold here and confirm the same warning as the trace panel.
- **Known gaps:** No model download. Throughput is a rolling average, not a benchmark.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:6`, frontend
- **Granularity:** One section with four controls.

---

### M7-SET-FE-147 — Settings: privacy and security, with the measured outbound count

**Type:** Story

**User Story**
- **Actor:** a suspicious user, which is the target user by definition.
- **User Need:** a statement of fact with a number behind it.
- **Business Value:** the number is the proof of the local-only constraint and it is worth showing.
- *As someone who does not take privacy claims on faith, I want a measured count of outbound requests, so that the promise has evidence attached.*

**Context / Background**
**Detailed Description:** The privacy section: the passphrase control with its no-recovery warning; **network activity stated as a fact rather than offered as a toggle**, with the live count of outbound requests from the proxy; and the connected databases with their read-only status. Any permitted destination — a user's own database — is shown separately so the local-mode zero stays meaningful.

**Scope**
- Passphrase control surfacing the feature built in M7-SEC-BE-151.
- Network activity statement with the proxy's live counts and recent refusals.
- Connected databases with read-only status and their permitted destinations listed distinctly.

**Out of Scope**
- The passphrase mechanism itself (M7-SEC-BE-151).

**Acceptance Criteria**
- **Acceptance Criteria:** Network activity is a statement with a live measured count, not a toggle. Refused requests are shown with their destinations. Permitted destinations for user databases are listed separately from the local-mode figure. Connected databases show read-only status.
- **Edge Cases:** The proxy unreadable — the count says unavailable, never zero. A non-zero refusal count — shown plainly with destinations, because hiding it would be the opposite of the point. No databases connected — the section says so rather than being empty.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §4 and §8.
- **Validation Rules:** The count must come from the proxy, never from the application.
- **Audit / Logging Requirements:** None for viewing.
- **Analytics Events:** Local counters only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user opens settings after a month and sees zero permitted outbound requests, which is the whole reason they installed it.

**Dependencies & Assumptions**
- **Dependencies:** M0-STACK-SEC-011, M4-CONN-BE-099, M7-SEC-BE-151.
- **API / Data Touchpoints:** Proxy counters; `sources`.
- **Assumptions:** Showing refusals openly builds more trust than hiding them, even when a refusal is a dependency misbehaving.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start and use Askwell normally for a session. Open settings and read the privacy section — confirm it states network activity as a fact and shows a zero permitted count. Trigger a refused request from a container and confirm the refusal count and destination appear. Connect a database and confirm it is listed as a permitted destination, separately, with read-only status.
- **Other scenarios:** Stop the proxy and confirm the count reads unavailable rather than zero.
- **Known gaps:** The passphrase control is inert until its own ticket lands.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** Critical
- **Labels / Component:** `phase:6`, frontend, security, `constraint:local-first`
- **Granularity:** One section with three displays.

---

### M7-SET-FE-148 — Settings: storage

**Type:** Story

**User Story**
- **Actor:** someone whose laptop is running low on space.
- **User Need:** to see what Askwell is using and to control it.
- **Business Value:** the product must be a polite guest on a laptop that is not primarily its.
- *As someone whose disk is nearly full, I want to see what Askwell is holding and prune it, so that I do not have to uninstall it to get space back.*

**Context / Background**
**Detailed Description:** The storage section: index size per source; the log budget with its default of two gigabytes or five percent of free disk, whichever is smaller, adjustable and showing current use; the interaction retention window defaulting to twelve months; export and prune as the archive path; and a statement of what happens at the limit — **ingestion stops first, asking keeps working** — said before it happens rather than discovered.

**Scope**
- Per-source index size.
- Log budget display and adjustment with current use.
- Retention window control.
- Export-and-prune entry point.
- The at-the-limit statement.

**Out of Scope**
- The budget enforcement itself (M7-LOG-BE-153).

**Acceptance Criteria**
- **Acceptance Criteria:** Index size is shown per source. The log budget is shown with current use and can be adjusted. The retention window can be changed. Export and prune is reachable. The section states what happens at the limit before it happens.
- **Edge Cases:** Free disk changing so the five-percent clause moves the effective budget — recalculated and shown, with the change explained. A source whose size cannot be computed — reported as unknown rather than zero. Reducing the budget below current use — accepted, with the immediate consequence stated and prune offered.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §5 and §8 log over budget; `../ux/library.md` §6 for per-source storage.
- **Validation Rules:** Decisions and memory are never pruned, at any budget.
- **Audit / Logging Requirements:** Budget and retention changes are decisions records.
- **Analytics Events:** Local counters only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user sees one imported dump is using most of their index space and deletes it rather than uninstalling.

**Dependencies & Assumptions**
- **Dependencies:** M7-LOG-BE-153, M1-LIB-FE-050.
- **API / Data Touchpoints:** `settings`; storage measurement.
- **Assumptions:** Per-source index size is computable without an expensive scan on every settings load.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with several sources indexed and a session of questions asked. Open settings and read the storage section — confirm per-source sizes look plausible, the log budget shows real current use, and the at-the-limit behaviour is stated. Lower the budget below current use and confirm the consequence is stated and prune is offered.
- **Other scenarios:** Fill the disk to change the five-percent clause and confirm the effective budget updates with an explanation.
- **Known gaps:** Size measurement is approximate for the vector index.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:6`, frontend
- **Granularity:** One section with five displays.

---

### M7-SET-FE-149 — Settings: about, licence, source and reporting a problem

**Type:** Task

**User Story**
- **Actor:** someone who wants to check the claim that this is open source.
- **User Need:** the version, the licence and the link to the source.
- **Business Value:** for a product whose claim is that nothing leaves the machine, the source is the proof, and hiding the link would be perverse.
- *As someone who chose this because it is auditable, I want the licence and the source link in the product, so that the claim is one click from being checked.*

**Context / Background**
**Detailed Description:** The about section: version derived from the single source of truth, licence, a link to the source repository, and how to report a problem — with the support boundary stated so expectations are set before someone is disappointed. Update checking appears here and is off by default.

**Scope**
- Version derived, never retyped.
- Licence and notices reachable in full, including bundled model weights.
- Source link and problem-reporting route with the support boundary stated.
- The update-checking control, off by default, with its payload stated — **the mechanism behind it is blocked.**

**Out of Scope**
- Update delivery itself — blocked (M7-UPDATE-BLOCKED-161).

**Acceptance Criteria**
- **Acceptance Criteria:** The version matches the source of truth. Licence and notices are reachable in full. The source link and reporting route are present. The support boundary is stated. Update checking is off by default and its payload is stated plainly.
- **Edge Cases:** Offline, so the source link cannot open — the address is shown as text so it can be copied, rather than a dead control. Notices very long — rendered in full and scrollable, never truncated, because a truncated notices file is a licence problem.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §7.
- **Validation Rules:** Update checking is off by default and never enabled by an upgrade.
- **Audit / Logging Requirements:** Enabling update checking is a decisions record.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A cautious user reads the notices, finds the bundled model weights and their licences listed, and is satisfied.

**Dependencies & Assumptions**
- **Dependencies:** M0-FOUND-DOC-008, M7-DOC-DOC-163, M7-DOC-DOC-164.
- **API / Data Touchpoints:** `VERSION`; notices file.
- **Assumptions:** The update control can exist and be off while the mechanism behind it is undecided; enabling it before the decision is made is refused with the reason.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, open settings and go to about. Confirm the version matches the repository's value. Open the licence and notices and read them in full, confirming bundled model weights are listed. Read the support boundary. Confirm update checking is off and that its description states exactly what would be sent.
- **Other scenarios:** Disconnect the network and confirm the source address is still readable as text.
- **Known gaps:** Update checking cannot be enabled because the mechanism is blocked; the control says so.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:6`, frontend, documentation
- **Granularity:** One section.

---

### M7-SET-FE-150 — Settings: online AI, visible and disabled

**Type:** Task

**User Story**
- **Actor:** someone wondering whether this will ever get a bigger model.
- **User Need:** to see the paid feature described and switched off.
- **Business Value:** hiding the paid feature until launch means nobody expects it; showing it disabled sets the expectation honestly.
- *As someone evaluating whether to invest my corpus in this, I want to see where it is going, so that a paid feature appearing later is not a surprise.*

**Context / Background**
**Detailed Description:** The online AI section ships visible and inert, explaining in plain terms what it will be — a larger cloud model for hard questions, paid by credit, chosen per conversation rather than globally — and stating that Askwell never asks for an API key from another provider. Everything in it is inert until the feature exists.

**Scope**
- The section with its explanation, visibly disabled.
- The statement about never asking for a third-party key.
- A placeholder for exactly what leaves the machine, which is filled when the open decision is answered.

**Out of Scope**
- Everything functional — the whole feature is M8 and partly blocked.

**Acceptance Criteria**
- **Acceptance Criteria:** The section is visible, clearly inert, and explains what the feature will be. It states that no third-party API key is ever requested. It states that the choice will be per conversation. Nothing in it can be enabled.
- **Edge Cases:** A user trying to enable it — a plain statement that it is not available yet, with no waiting list and no email field, because there is nothing to sign into. The exact-payload statement not yet decided — the section says it will be stated before anything is sent, rather than guessing.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §3 and §8 online AI pre-launch.
- **Validation Rules:** No field in this section may collect anything.
- **Audit / Logging Requirements:** None.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A user reads that the product will offer paid online AI per conversation and decides that is acceptable, months before it exists.

**Dependencies & Assumptions**
- **Dependencies:** M7-SET-FE-149.
- **API / Data Touchpoints:** None.
- **Assumptions:** Describing an undecided pricing model is avoided entirely — the section describes the shape, not the price.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, open settings and read the online AI section. Confirm it explains the feature, is visibly disabled, and offers no field to fill. Attempt to enable it and confirm a plain statement rather than a form.
- **Other scenarios:** Confirm no part of it makes a network request.
- **Known gaps:** Pricing is undecided and deliberately absent. The exact payload is undecided.

**Effort & Granularity Check**
- **Estimate:** 1–2 hours · **Priority:** Medium
- **Labels / Component:** `phase:6`, frontend
- **Granularity:** One inert section.

---

### M7-SEC-BE-151 — Passphrase: set, unlock, and no recovery

**Type:** Story

**User Story**
- **Actor:** someone who travels with a laptop full of client files.
- **User Need:** their corpus encrypted so a stolen laptop is not a breach.
- **Business Value:** this is the feature that makes a stolen laptop not a data breach, and a recovery path would defeat it entirely.
- *As someone who carries confidential material, I want a passphrase that encrypts my library, so that losing the laptop is losing hardware rather than losing a client.*

**Context / Background**
**Detailed Description:** An optional passphrase, off by default. Setting it explains that losing it means losing the library, because there is no recovery — a recovery path would defeat the purpose. On restart, the passphrase is required before anything decrypts. Export is offered while still unlocked, because that is the only moment it is possible.

**Scope**
- Set, change and remove the passphrase, with strength feedback.
- The no-recovery warning before confirming.
- Unlock prompt on restart before anything decrypts.
- Export offered while unlocked, particularly at the moment a user considers removing or forgetting it.

**Out of Scope**
- The encryption of the corpus itself (M7-SEC-BE-152).

**Acceptance Criteria**
- **Acceptance Criteria:** Setting a passphrase requires acknowledging that there is no recovery. Restarting prompts for it before anything decrypts. A wrong passphrase refuses without revealing whether it was close. Removing the passphrase decrypts and states the consequence. There is no recovery mechanism anywhere.
- **Edge Cases:** A forgotten passphrase — the only path is reset, which destroys the library, and this is said clearly with export offered while still unlocked. A passphrase set while ingestion is running — ingestion pauses and resumes after unlock rather than writing unencrypted. Backup taken with a passphrase and restored on a machine without it — unrecoverable, and the restore says so, which is the interaction the backup work must handle.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §4 and §8 passphrase being set and forgotten; `../states-and-edge-cases.md` §1 passphrase set and app restarted.
- **Validation Rules:** No recovery path may be added, ever.
- **Audit / Logging Requirements:** Setting, changing and removing are decisions records without the value.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A user sets a passphrase before a conference trip and their laptop is stolen from a hotel room; the corpus is unreadable.

**Dependencies & Assumptions**
- **Dependencies:** M4-CONN-SEC-098.
- **API / Data Touchpoints:** `settings`; key derivation.
- **Assumptions:** The key derivation already built for credentials extends to include the passphrase without re-entering credentials.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, open settings and set a passphrase, reading the no-recovery warning before confirming. Restart Askwell and confirm the prompt appears before any content is visible. Enter it wrongly and read the refusal. Enter it correctly and confirm everything works. Remove it and confirm the consequence is stated.
- **Other scenarios:** Set a passphrase during an active import and confirm ingestion pauses rather than writing unencrypted.
- **Known gaps:** No recovery, deliberately. Backup interaction is handled in the backup tickets.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:6`, security
- **Granularity:** One feature with three operations.

---

### M7-SEC-BE-152 — Encryption at rest for documents and credentials

**Type:** Story

**User Story**
- **Actor:** someone whose disk could be imaged.
- **User Need:** the indexed content encrypted, not just the credentials.
- **Business Value:** the index contains the content; encrypting credentials while leaving the corpus in the clear would be theatre.
- *As someone whose extracted contract text sits in a database on my disk, I want that encrypted too, so that the protection is real rather than partial.*

**Context / Background**
**Detailed Description:** When a passphrase is set, chunk content and stored credentials are encrypted at rest with the derived key. The vector index and the full-text index carry inherent leakage that cannot be fully removed on a single-machine product, and the documentation states this honestly rather than overclaiming.

**Scope**
- Encryption of chunk content and credentials when a passphrase is set.
- Transparent decryption on the query path with acceptable performance.
- Honest documentation of what remains readable — index structures and metadata.
- Migration when a passphrase is set after content exists, and when it is removed.

**Out of Scope**
- Encrypting the vector index, which would break retrieval on a local machine.

**Acceptance Criteria**
- **Acceptance Criteria:** With a passphrase set, chunk content is unreadable in the database without the key. Queries still work with acceptable latency. Setting a passphrase on an existing corpus migrates it with progress. Removing it decrypts. The documentation states precisely what remains readable.
- **Edge Cases:** Migration interrupted — resumes rather than leaving a half-encrypted corpus that cannot be read either way. Performance materially degraded on a light profile — measured and stated, so the user chooses knowingly. A backup taken mid-migration — refused, with the reason.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §4.
- **Validation Rules:** Content is never written unencrypted while a passphrase is set.
- **Audit / Logging Requirements:** Migration start and completion are decisions records.
- **Analytics Events:** Local only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A stolen laptop's disk is imaged and the extracted contract text is unreadable, while the fact that forty documents exist is not concealed — which the documentation says plainly.

**Dependencies & Assumptions**
- **Dependencies:** M7-SEC-BE-151.
- **API / Data Touchpoints:** `chunks.content`; `sources.config_encrypted`.
- **Assumptions:** Encrypting the vector column is not attempted; retrieval needs it readable, and pretending otherwise would be the overclaim the security section warns against.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with an indexed corpus. Set a passphrase and watch the migration complete. Stop Askwell, inspect the database directly, and confirm chunk content is not readable. Start Askwell, unlock, and confirm questions still work at acceptable speed. Remove the passphrase and confirm content is readable again.
- **Other scenarios:** Interrupt the migration and confirm it resumes.
- **Known gaps:** Index structures and metadata remain readable, stated in the documentation rather than hidden.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** High
- **Labels / Component:** `phase:6`, security
- **Granularity:** Encryption plus migration plus honest documentation. Upper bound.

---

### M7-LOG-BE-153 — Log storage budget with staged degradation

**Type:** Story

**User Story**
- **Actor:** someone whose disk filled while Askwell was importing.
- **User Need:** the product to degrade in the right order rather than stopping.
- **Business Value:** the instinct is to block everything at the limit; blocking the cheapest and most valuable operation last is what keeps the product usable while the user sorts out disk space.
- *As someone who has run out of disk, I want to keep asking questions while I clear space, so that a full disk is an inconvenience rather than an outage.*

**Context / Background**
**Detailed Description:** Four stages: a budget set at install, defaulting to two gigabytes or five percent of free disk whichever is smaller; a persistent dismissible notice at eighty percent offering export, archive or prune; **new ingestion refused first at the hard limit while asking keeps working**; and only when the decisions store itself cannot be written does an action fail.

**Scope**
- Budget measurement across the interaction store and the trace buffer.
- The eighty-percent notice, persistent and dismissible, never a modal.
- Ingestion refusal at the hard limit with asking unaffected.
- Action failure only when the decisions store cannot be written.

**Out of Scope**
- Export and prune themselves (M7-LOG-BE-155).

**Acceptance Criteria**
- **Acceptance Criteria:** At eighty percent a persistent dismissible notice appears offering export, archive or prune. At the hard limit new ingestion is refused with a clear reason while questions still work. Only a decisions-store write failure fails an action. Traces never fail an action.
- **Edge Cases:** The disk filling from outside Askwell — the same staging applies, since the budget is about total available space as well as the configured cap. Budget lowered below current use — the notice appears immediately. A large export while at the limit — permitted, because export is the way out.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../states-and-edge-cases.md` §1 log storage at eighty percent, at the hard limit, decisions store cannot be written, disk full.
- **Validation Rules:** Decisions and memory are never pruned at any budget.
- **Audit / Logging Requirements:** Stage transitions are logged; budget changes are decisions records.
- **Analytics Events:** Local counters only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user hits the limit mid-import, sees ingestion refused with a clear reason, keeps asking questions all afternoon, and prunes the log that evening.

**Dependencies & Assumptions**
- **Dependencies:** M0-DATA-OBS-015, M1-ADD-ING-025.
- **API / Data Touchpoints:** `settings`; store sizes.
- **Assumptions:** The decisions store stays in the kilobytes, which is what makes the strict guarantee hold in practice rather than becoming a support ticket.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, set a very small log budget so the stages are reachable. Use Askwell until the eighty-percent notice appears — confirm it is persistent and dismissible and not a modal. Continue to the hard limit and try to add a source: confirm it is refused with a clear reason. Then ask a question and confirm it works normally. Finally make the decisions table unwritable and change a setting — confirm the action fails with a stated reason.
- **Other scenarios:** Fill the disk from outside Askwell and confirm the same staging.
- **Known gaps:** Prune and export are the next tickets.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:6`, backend, observability, `constraint:audit`
- **Granularity:** Four stages sharing one measurement.

---

### M7-LOG-BE-154 — Interaction retention window and prune

**Type:** Task

**User Story**
- **Actor:** someone who wants last year's questions available but not five years of them.
- **User Need:** a retention window they control.
- **Business Value:** long enough that last year's question is findable, short enough that the store does not grow without limit.
- *As someone who occasionally looks back at what I asked about a client last year, I want a year kept, so that the store is useful without being endless.*

**Context / Background**
**Detailed Description:** Interactions are retained for a rolling window, defaulting to twelve months and user-configurable. Pruning removes interactions outside the window after export, and the hash chain remains verifiable across the prune boundary by recording what was pruned. **Decisions and memory are never pruned.**

**Scope**
- Retention window with a configurable default.
- Prune of interactions outside the window, only after export.
- Chain integrity across a prune, with the prune itself recorded.

**Out of Scope**
- Pruning decisions or memory — forbidden.

**Acceptance Criteria**
- **Acceptance Criteria:** Interactions older than the window are prunable after export. Decisions and memory are never touched. Verification still succeeds after a prune, with the prune boundary recorded so the chain is explicable rather than merely broken. Changing the window changes what is prunable.
- **Edge Cases:** Prune attempted without export — refused, with export offered, because pruning unexported records destroys the user's own history. Prune interrupted — resumable, with the chain intact either way. A window shorter than the age of everything — refused unless the user confirms they understand, because it would prune nearly everything.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §5.
- **Validation Rules:** Export before prune, always.
- **Audit / Logging Requirements:** The prune is a decisions record naming the range removed.
- **Analytics Events:** Local only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user exports and prunes two-year-old interactions, halving the store, and verification still passes.

**Dependencies & Assumptions**
- **Dependencies:** M7-LOG-BE-155, M0-DATA-OBS-015.
- **API / Data Touchpoints:** `audit_interactions`; `settings`.
- **Assumptions:** Recording the prune boundary in the chain is enough to keep verification meaningful; a chain that simply stops at a gap would be indistinguishable from tampering.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with a log containing dated interactions. Attempt to prune without exporting and confirm refusal with export offered. Export, then prune, and confirm the store shrinks. Run verification and confirm it passes with the prune boundary explained. Confirm memory and decisions are untouched.
- **Other scenarios:** Set a very short window and confirm the extra confirmation.
- **Known gaps:** Pruned interactions exist only in the export from then on.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:6`, backend, `constraint:audit`
- **Granularity:** One window and one prune.

---

### M7-LOG-BE-155 — Log export as a background job, with the chain and a verifier

**Type:** Story

**User Story**
- **Actor:** a consultant who needs to show a client what was asked of their confidential corpus.
- **User Need:** an export that someone else can verify.
- **Business Value:** the log is the user's own record and must be exportable, and an export nobody can verify is just a text file.
- *As someone who may have to produce a record, I want an export with its hash chain and a way to check it, so that the record is verifiable rather than merely asserted.*

**Context / Background**
**Detailed Description:** Export interactions and decisions in open formats, with the hash chain included and a verification tool that a third party can run. It is a background job with progress and a result when ready, because a year of interactions is not a synchronous operation. Exporting the interaction window is also the archive path before pruning.

**Scope**
- Background export job with progress and a result.
- Open formats for interactions and decisions, with the chain included.
- A verification tool shipped with the export, runnable without Askwell.
- Filtered export by date range.

**Out of Scope**
- Exporting the corpus itself (M7-DATA-FE-160).

**Acceptance Criteria**
- **Acceptance Criteria:** Export runs in the background with progress and produces a file in an open format containing the records and the chain. The bundled verifier confirms the chain on another machine without Askwell installed. A date-range export works. Export is possible while at the log budget limit.
- **Edge Cases:** Export interrupted — restartable, and no partial file is presented as complete. A very large export — streamed to disk rather than assembled in memory. Export while a passphrase is set — the export is written decrypted, and the user is warned before it is written, since an exported file is outside the protection.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §6 and §8 export running; `../states-and-edge-cases.md` §6 log export large range.
- **Validation Rules:** The chain must be included, or it is not an export.
- **Audit / Logging Requirements:** The export is a decisions record naming the range.
- **Analytics Events:** Local only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A consultant hands a client an export and a verifier, and the client's own technical person confirms the chain.

**Dependencies & Assumptions**
- **Dependencies:** M0-DATA-OBS-015.
- **API / Data Touchpoints:** Both audit tables.
- **Assumptions:** A small standalone verifier is shippable alongside the export and does not need Askwell's dependencies.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start after a session of use. Open settings and start a log export, confirming it runs in the background with progress while you continue using Askwell. When it completes, copy the export and the verifier to another machine with no Askwell installed and run the verifier — confirm it reports the chain intact. Then alter one record in the exported file and re-run — confirm it names the break.
- **Other scenarios:** Export with a passphrase set and confirm the warning before writing.
- **Known gaps:** The export is plain and unencrypted; protecting it is the user's responsibility, stated at the time.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** High
- **Labels / Component:** `phase:6`, backend, `constraint:audit`
- **Granularity:** Job plus format plus verifier. Upper bound.

---

### M7-LOG-FE-156 — Verification surface reporting where the chain breaks

**Type:** Task

**User Story**
- **Actor:** someone who wants to check their own log has not been altered.
- **User Need:** a verification they can run and a plain report.
- **Business Value:** the guarantee is tamper-evidence, and evidence that is not surfaced is not evidence.
- *As someone relying on this record, I want to run the check and see the result, so that the tamper-evidence is something I can actually use.*

**Context / Background**
**Detailed Description:** A verify action in settings that runs the chain check across both stores and reports plainly: intact, or broken at a named record with what that means — that the application never rewrites history, so a break indicates something outside Askwell changed the file. **It is tamper-evident, never described as immutable.**

**Scope**
- Verify action with progress for a large log.
- Plain reporting of intact or broken, naming the record and the date.
- Explanatory copy stating what a break means and what it does not.

**Out of Scope**
- Repairing a broken chain — it cannot be repaired, and offering to would be dishonest.

**Acceptance Criteria**
- **Acceptance Criteria:** Verify runs across both stores and reports intact or names the first break with its date. The explanation states that the application never rewrites history and that a break indicates external change. The word immutable appears nowhere.
- **Edge Cases:** A break at a prune boundary — reported as an explained boundary rather than tampering. A very large log — progress shown and the operation is interruptible. Both stores broken — both reported.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §6 and §8 hash chain broken; `../states-and-edge-cases.md` §6.
- **Validation Rules:** Never describe the log as immutable.
- **Audit / Logging Requirements:** Verification runs are logged with their result.
- **Analytics Events:** Local only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user runs verify out of curiosity, sees it intact, and understands what the guarantee actually is.

**Dependencies & Assumptions**
- **Dependencies:** M7-LOG-BE-155, M0-DATA-OBS-015.
- **API / Data Touchpoints:** Both audit tables.
- **Assumptions:** Verification over a year of interactions completes in a tolerable time with progress shown.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start after using Askwell for a session. Open settings and run verify — confirm it reports the chain intact and explains what that means. Alter a record directly in the database and run verify again — confirm it names that record and its date and explains that something outside Askwell changed it. Confirm the word immutable is not used anywhere.
- **Other scenarios:** Prune, then verify, and confirm the boundary is explained rather than reported as tampering.
- **Known gaps:** A break cannot be repaired, and no repair is offered.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:6`, frontend, `constraint:audit`
- **Granularity:** One action and two reports.

---

### M7-BACKUP-BE-157 — Backup that excludes what can be regenerated

**Type:** Story

**User Story**
- **Actor:** someone about to replace their laptop.
- **User Need:** a backup small enough to be practical.
- **Business Value:** including model weights and the vector index would make a backup tens of gigabytes and therefore something nobody takes.
- *As someone changing machines, I want a backup I can actually copy onto a drive, so that I take one at all.*

**Context / Background**
**Detailed Description:** Backup includes sources and their configuration, documents metadata and extracted content, memory, schema notes, clarifications, conversations, citations, fact usage and the audit stores. It **excludes model weights, the trace ring buffer and the vector index**, because all three are large and regenerable, and it states the re-embed cost plainly rather than hiding it.

**Scope**
- Backup job producing one portable artefact with a manifest and the version it was taken on.
- Explicit exclusion of weights, traces and the vector index.
- The re-embed cost estimated and stated at backup time and again at restore.
- Backup while a passphrase is set, with the key handling stated.

**Out of Scope**
- Restore (M7-BACKUP-BE-158).
- Backing up the user's original files — they are never copied, and the backup says so.

**Acceptance Criteria**
- **Acceptance Criteria:** A backup produces one artefact containing everything except weights, traces and the vector index. The artefact carries a manifest and the version. The re-embed cost is estimated and stated. The backup states plainly that the user's own files are not included, because they were never copied.
- **Edge Cases:** Backup during ingestion — either refused with the reason or taken at a consistent point, never a torn snapshot. Backup with a passphrase set — the encrypted content is included as encrypted and the restore requires the passphrase, stated at backup time. Insufficient space for the artefact — refused before starting with the space needed.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §6.
- **Validation Rules:** The artefact must be internally consistent — no half-written table.
- **Audit / Logging Requirements:** Backup is a decisions record.
- **Analytics Events:** Local only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user takes a backup of a large corpus and it is a manageable size because the vector index was excluded, with the re-embed time stated up front.

**Dependencies & Assumptions**
- **Dependencies:** M7-SEC-BE-152, M7-LOG-BE-155.
- **API / Data Touchpoints:** All tables except the vector column; the trace buffer is excluded.
- **Assumptions:** Re-embedding on restore is acceptable because it is time rather than data loss, and stating the cost plainly is what makes that a fair trade.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with a corpus, memory and conversations. Open settings and take a backup. Read the stated re-embed cost and the statement that original files are not included. Confirm the artefact size is far smaller than the index. Confirm the manifest names the version.
- **Other scenarios:** Attempt a backup with insufficient space and confirm refusal before starting.
- **Known gaps:** Restore is the next ticket; a backup with no tested restore is not yet a backup.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:6`, backend
- **Granularity:** One job with one manifest and one exclusion rule. Upper bound.

---

### M7-BACKUP-BE-158 — Restore, with the re-embed cost stated at the moment it matters

**Type:** Story

**User Story**
- **Actor:** someone setting up their replacement laptop.
- **User Need:** their corpus and memory back, and to know what it will cost in time.
- **Business Value:** the acceptance criterion for the phase is that a backup taken on one machine restores onto another with corpus and memory intact.
- *As someone moving to a new machine, I want my memory and my sources back, so that six months of teaching Askwell is not lost.*

**Context / Background**
**Detailed Description:** Restore reads the artefact, applies migrations if the version differs, restores everything included, and queues re-embedding of the corpus with the cost stated plainly before the user commits. Where original files are not present at their recorded paths on the new machine, documents report as missing rather than deleted and the roots can be re-registered. Credentials require re-entry because the per-install secret differs, and a passphrase-protected backup requires its passphrase.

**Scope**
- Restore with version checking and migration.
- Re-embed queued with the cost stated before committing.
- Missing-original handling and root re-registration on the new machine.
- Credential re-entry and passphrase requirement, both stated up front.

**Out of Scope**
- Partial or selective restore.

**Acceptance Criteria**
- **Acceptance Criteria:** A backup restores onto a clean machine with sources, memory, clarifications, conversations, citations and the audit stores intact and verifiable. The re-embed cost is stated before the user commits and re-embedding then runs with progress. Missing originals report as missing with a re-registration path. Credentials require re-entry, stated in advance.
- **Edge Cases:** A backup from a newer version — refused with the version named rather than partially applied. A passphrase-protected backup with no passphrase — refused with a clear statement that it is unrecoverable, which is the interaction the settings screen flags as open. Restore onto a machine with existing data — refused or requires explicit replacement, never merged silently. Re-embedding interrupted — resumes.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §6 and §9 passphrase and backup interaction; `../ux/source-viewer.md` §4 file moved for the missing-original case.
- **Validation Rules:** Never merge a restore into existing data silently.
- **Audit / Logging Requirements:** Restore is a decisions record; the restored chain is verified as part of the restore and the result is reported.
- **Analytics Events:** Local only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user restores onto a new laptop, re-registers their documents folder, waits two hours for re-embedding, and everything Askwell learned is still there.

**Dependencies & Assumptions**
- **Dependencies:** M7-BACKUP-BE-157, M1-VIEW-BE-049, M4-CONN-SEC-098.
- **API / Data Touchpoints:** All restored tables; roots registry.
- **Assumptions:** Re-embedding on restore is the accepted cost of excluding the vector index, and stating it plainly at restore is what makes it acceptable.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Take a backup on a machine with a real corpus and memory. On a clean second machine, install Askwell and restore from it. Read the stated re-embed cost before committing. After restore, confirm memory facts are present with their history, conversations are intact with their citations, and documents report as missing until you re-register the folder. Re-register, wait for re-embedding, then ask a question you asked on the first machine and confirm the same answer with the same citation. Run log verification and confirm the chain is intact.
- **Other scenarios:** Attempt a restore from a newer version and confirm refusal. Attempt a passphrase-protected restore without the passphrase and confirm the clear statement.
- **Known gaps:** No selective restore. Credentials always require re-entry.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:6`, backend
- **Granularity:** Restore plus re-embed plus three stated consequences. Upper bound.

---

### M7-BACKUP-TEST-159 — Tested restore, every release

**Type:** Story

**User Story**
- **Actor:** the maintainer publishing a release.
- **User Need:** the restore exercised on a clean machine before anyone relies on it.
- **Business Value:** an untested restore is a backup that does not exist.
- *As someone whose users will trust this with six months of work, I want the restore proven every release, so that the first real test is not somebody's emergency.*

**Context / Background**
**Detailed Description:** A documented release procedure: take a backup on a machine with a representative corpus, restore it onto a clean machine of a different platform where possible, and verify corpus, memory, conversations, citations and the audit chain. Record the result per release. This is a gate, not a wish.

**Scope**
- The documented procedure with its verification checklist.
- Cross-platform restore where the platforms allow.
- Recorded pass or fail per release, with the artefact retained.

**Out of Scope**
- Automating the whole procedure — the manual walkthrough is the point.

**Acceptance Criteria**
- **Acceptance Criteria:** The procedure is documented and executable by someone who did not write it. A restore onto a clean machine reproduces corpus, memory, conversations and citations, and verification passes. The result is recorded per release, and a failure blocks the release.
- **Edge Cases:** Cross-platform restore where paths differ fundamentally — the missing-original path is exercised deliberately, since it is the normal case. A backup from the previous release restored onto the new one — included, because that is the real upgrade path. A failure — blocks the release rather than being noted.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** As M7-BACKUP-BE-158.
- **Validation Rules:** A release with a failed restore test does not ship.
- **Audit / Logging Requirements:** The result is part of the release record.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A schema change breaks restore from the previous version; the test catches it before release rather than after.

**Dependencies & Assumptions**
- **Dependencies:** M7-BACKUP-BE-158, M7-PACK-DEPLOY-141.
- **API / Data Touchpoints:** The full data set.
- **Assumptions:** A representative corpus fixture is maintained for this purpose rather than assembled each time.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** This ticket is the walkthrough. Using the representative fixture corpus, take a backup on the current release. On a clean machine of a different platform, install and restore, following only the written procedure. Work through the checklist: memory present with history, conversations with working citations, sources listed, chain verified, a known question answered identically after re-embedding. Record the result.
- **Other scenarios:** Restore a previous release's backup onto the new build and confirm migrations apply.
- **Known gaps:** Largely manual and takes a working session; that is accepted for a release gate.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:6`, test, deployment
- **Granularity:** One procedure and one checklist.

---

### M7-DATA-FE-160 — Export everything, delete memory, reset Askwell

**Type:** Story

**User Story**
- **Actor:** someone who chose this product for sovereignty and intends to check.
- **User Need:** a complete export in open formats and a genuine way to delete everything.
- **Business Value:** a free, open-source, local product with a lock-in export is a contradiction, and the users who chose it are exactly the ones who will check.
- *As someone who chose this because I own my data, I want a complete export and a real delete, so that the claim is testable.*

**Context / Background**
**Detailed Description:** The data section: export everything — sources list, memory, conversations, logs with the chain and verifier — in open formats as a background job; export the log alone; delete a source; delete all memory with a confirmation naming the count and stating it cannot be undone; reset Askwell entirely, **stating plainly that original files are never touched**; and verify the log.

**Scope**
- Export everything as a background job in open formats.
- Delete all memory with the count and the irreversibility stated.
- Reset with the original-files statement and a clear description of what is destroyed.
- The section wiring the already-built log export and verification.

**Out of Scope**
- Import of an export — that is restore, and memory import across machines is not v1.

**Acceptance Criteria**
- **Acceptance Criteria:** Export everything produces open-format files covering sources, memory, conversations and logs with the chain, as a background job. Delete all memory confirms with the count and cannot be undone. Reset destroys Askwell's data and states plainly that original files are untouched, and they are. Verification is reachable from here.
- **Edge Cases:** Reset while ingestion is running — ingestion stops first and the reset completes cleanly. Export while a passphrase is set — warned that the export is unprotected before writing. Reset on a machine with registered roots — the roots are forgotten and the files are untouched, and this is stated explicitly because it is the thing a user fears most.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §6; `../ux/library.md` §4 for source deletion.
- **Validation Rules:** Export must be genuinely complete and genuinely open.
- **Audit / Logging Requirements:** Export, delete-all-memory and reset are decisions records — and reset destroys the store that holds them, which is stated.
- **Analytics Events:** Local only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A cautious user exports everything on day two, opens the files in a text editor, confirms they are readable and complete, and then trusts the product.

**Dependencies & Assumptions**
- **Dependencies:** M7-LOG-BE-155, M3-MEM-FE-084, M2-DELETE-FE-062.
- **API / Data Touchpoints:** All tables; the file system.
- **Assumptions:** Open formats mean formats readable without Askwell — plain text, delimited data and a documented structure.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with a corpus, memory and conversations. Open settings and export everything, confirming it runs in the background. Open the resulting files in an ordinary editor and confirm memory facts, conversations and log records are readable. Then delete all memory, confirming the count is named and the irreversibility stated, and confirm memory is empty afterwards. Finally reset Askwell, read the statement about original files, complete it, and confirm the indexed files on disk are all still there and unmodified.
- **Other scenarios:** Export with a passphrase set and confirm the warning.
- **Known gaps:** There is no import of an export; restoring is the backup path.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:6`, frontend
- **Granularity:** One section with four actions.

---

### M7-UPDATE-BLOCKED-161 — Update delivery mechanism **[BLOCKED]**

**Type:** Spike

**User Story**
- **Actor:** someone running a version with a security fix available.
- **User Need:** to learn a new version exists without the product phoning home by default.
- **Business Value:** an open-source product whose users never learn about a security fix is a real problem; a silent check contradicts the product's central constraint.
- *As someone who installed this for privacy, I want to learn about updates without being tracked, so that staying current is not a trade against the reason I chose it.*

**Context / Background**
**Detailed Description:** **This ticket is blocked on an open product decision** — how a free local install learns that a new version exists without phoning home by default. The decision is recorded as open in the business case and in the settings specification. Realistic shapes exist — an explicit opt-in check with the payload stated, a manual check the user initiates, an out-of-band notification channel, or installer-managed updates through the platform's own mechanism — but choosing one is a product call, not an engineering default. **Do not start this work. Do not pick a default.**

**Scope**
- Nothing is implemented until the decision is made.
- When unblocked: the mechanism, its payload, its frequency, and its interaction with the egress proxy's permitted destinations.

**Out of Scope**
- Any implementation while blocked.
- Any silent check, under any circumstances.

**Acceptance Criteria**
- **Acceptance Criteria:** This ticket cannot be accepted while blocked. When unblocked, the mechanism must be off by default, must state exactly what is sent before it is enabled, and must be recorded as a decision-log entry with the alternatives that were rejected.
- **Edge Cases:** All deferred with the decision.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §7 and §9 — the control exists and is off; the mechanism behind it does not.
- **Validation Rules:** No update check may be enabled by default or by an upgrade.
- **Audit / Logging Requirements:** Enabling a check is a decisions record.
- **Analytics Events:** None — an update check is not analytics and must never carry anything beyond what is stated.

**Real-World Example Scenarios**
- Deferred with the decision.

**Dependencies & Assumptions**
- **Dependencies:** **Blocked on the open update-delivery decision.**
- **API / Data Touchpoints:** Would touch the egress proxy's permitted destinations.
- **Assumptions:** None may be made. Picking a default here would build a phase of work against the wrong assumption.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Not applicable while blocked. When unblocked, the walkthrough must include installing, confirming no check occurs by default, enabling the check, reading exactly what will be sent, and verifying with a network capture that nothing beyond that is sent.
- **Known gaps:** The entire mechanism. Users currently learn about updates only by looking.

**Effort & Granularity Check**
- **Estimate:** Not estimable while blocked. A spike to write up the options and a recommendation is 2–3 hours. · **Priority:** High
- **Labels / Component:** `phase:6`, `blocked:decision`, `constraint:local-first`, deployment
- **Granularity:** Blocked. Do not start.

---

### M7-UPDATE-BLOCKED-162 — Update notification surface **[BLOCKED]**

**Type:** Spike

**User Story**
- **Actor:** someone whose install is three versions behind.
- **User Need:** to be told, in a way consistent with the product's promise.
- **Business Value:** the same as the mechanism — a user who never learns about a security fix is a real problem.
- *As someone running an old version, I want to be told there is a newer one, so that I am not unknowingly running something with a known problem.*

**Context / Background**
**Detailed Description:** **Blocked on the same open decision as M7-UPDATE-BLOCKED-161.** The surface — how a discovered update is presented, how a user applies it, and what happens to their data across the upgrade — cannot be specified until the delivery mechanism is chosen.

**Scope**
- Nothing while blocked.
- When unblocked: notification presentation, the apply flow, and the data-safety statement across an upgrade.

**Out of Scope**
- Any implementation while blocked. Any nagging, whatever the mechanism.

**Acceptance Criteria**
- **Acceptance Criteria:** Cannot be accepted while blocked. When unblocked: the notification must never nag, must never block use, and the upgrade must state what happens to the user's data before it runs.
- **Edge Cases:** Deferred.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §7.
- **Validation Rules:** No modal on launch, ever.
- **Audit / Logging Requirements:** An applied upgrade is a decisions record.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- Deferred with the decision.

**Dependencies & Assumptions**
- **Dependencies:** **Blocked on the open update-delivery decision**, and on M7-UPDATE-BLOCKED-161.
- **API / Data Touchpoints:** Deferred.
- **Assumptions:** None may be made.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Not applicable while blocked.
- **Known gaps:** The entire surface.

**Effort & Granularity Check**
- **Estimate:** Not estimable while blocked. · **Priority:** Medium
- **Labels / Component:** `phase:6`, `blocked:decision`, frontend
- **Granularity:** Blocked. Do not start.

---

### M7-DOC-DOC-163 — Licence and notices file covering bundled model weights

**Type:** Task

**User Story**
- **Actor:** someone deciding whether they can use this at work.
- **User Need:** every licence in the distribution listed accurately.
- **Business Value:** the licence position was chosen deliberately and a dependency with the wrong licence would undo it; bundled model weights carry their own terms that are easy to forget.
- *As someone whose employer asks about licences, I want a complete notices file, so that I can answer without reading the source.*

**Context / Background**
**Detailed Description:** Produce and maintain a notices file covering every bundled dependency and, critically, the **model weights** — the language model, the embedding model, the reranker, the transcription model, the voice activity detector, the synthesis model and the OCR training data each carry their own terms. Verify that nothing in the distribution conflicts with the project's chosen licence, which is why one PDF library was rejected in favour of another.

**Scope**
- Notices generation for code dependencies on both sides.
- Manual entries for each bundled model with its licence and source.
- A check that fails the release if a dependency's licence is on a disallowed list.
- The file reachable from the about section.

**Out of Scope**
- Legal advice — this is an accurate inventory, not an opinion.

**Acceptance Criteria**
- **Acceptance Criteria:** The notices file lists every code dependency and every bundled model with its licence. A newly added dependency with a conflicting licence fails the check. The file is reachable in the product and in the repository.
- **Edge Cases:** A model whose licence has usage restrictions rather than a standard form — recorded verbatim rather than summarised, since summarising a licence is how a restriction gets lost. A transitive dependency with an unclear licence — flagged for a decision rather than assumed permissive. A model swapped by the user — their own responsibility, stated.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §7 about.
- **Validation Rules:** A disallowed licence in the distribution blocks the release.
- **Audit / Logging Requirements:** None.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A user's employer asks whether any component carries a copyleft network clause, and the notices file answers it in one place.

**Dependencies & Assumptions**
- **Dependencies:** M7-OFFLINE-DEPLOY-144.
- **API / Data Touchpoints:** None.
- **Assumptions:** Model weight licences are the highest-risk item because they are easy to overlook and are not covered by dependency tooling.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Install the product, open settings, go to about, and open the notices. Read through and confirm every bundled model is listed with its licence and its source. Then add a dependency with a disallowed licence on a branch and confirm the check fails the build.
- **Other scenarios:** Confirm the file in the repository matches the one in the product.
- **Known gaps:** This is an inventory, not legal review.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:6`, documentation
- **Granularity:** One file plus one check.

---

### M7-DOC-DOC-164 — Stated support boundary and issue triage

**Type:** Task

**User Story**
- **Actor:** someone about to open an issue.
- **User Need:** to know what a single maintainer will and will not answer.
- **Business Value:** free and open sets a support expectation a single maintainer cannot meet, and a stated boundary must exist before the first release rather than being discovered afterwards.
- *As someone with a problem, I want to know what kind of help exists, so that my expectation matches reality.*

**Context / Background**
**Detailed Description:** Write and publish the support boundary: what is answered, what is not, expected response behaviour, and what a good report contains — including the version, the platform, the profile and a copied trace. Set up issue templates and a triage convention so reports arrive with what is needed. State plainly that this is a single-maintainer project.

**Scope**
- The support boundary document, reachable from the product and the repository.
- Issue templates for a bug, a question and a feature request, each requesting version, platform, profile and trace where relevant.
- A triage convention with labels and a stated cadence.

**Out of Scope**
- Any commitment to a response time that cannot be met.

**Acceptance Criteria**
- **Acceptance Criteria:** The support boundary is published and reachable from the about section. Issue templates request the information a report needs. The boundary states clearly what is out of scope. Nothing promises a response time that a single maintainer cannot honour.
- **Edge Cases:** A security report — a separate, clearly named route with a different expectation, because burying it in general triage is wrong. A report about a user's own database or hardware — named as out of scope with a pointer to where it belongs. A report with no version and no trace — the template makes that hard, and the triage convention says what to ask for.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §7 report a problem.
- **Validation Rules:** The boundary must be honest rather than generous.
- **Audit / Logging Requirements:** None.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A user opens an issue with their version, platform, profile and a copied trace, and the maintainer diagnoses it without a round trip.

**Dependencies & Assumptions**
- **Dependencies:** M5-TRACE-FE-121, M7-SET-FE-149.
- **API / Data Touchpoints:** None.
- **Assumptions:** A stated boundary reduces disappointment more than an unstated ambition raises satisfaction.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** From a fresh install, open settings, go to about, and follow the report-a-problem route. Confirm it leads to the boundary and the templates. Open a bug report through the template and confirm it asks for version, platform, profile and trace, and that the version is easy to find in the product. Confirm the security route is separate and named.
- **Other scenarios:** Read the boundary as someone new and confirm it is unambiguous about what is not covered.
- **Known gaps:** No response-time commitment, deliberately.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** Critical
- **Labels / Component:** `phase:6`, documentation
- **Granularity:** One document and three templates.

---

### M7-OPS-DOC-165 — Rollback, incident and crash-report readiness that respects the local-only constraint

**Type:** Task

**User Story**
- **Actor:** the maintainer at the moment a release turns out to be broken.
- **User Need:** a rehearsed way to get users back to a working version.
- **Business Value:** rollback preparedness discovered during an incident is not preparedness.
- *As the only person who can fix a bad release, I want the rollback path written down before I need it, so that an incident is a procedure rather than an improvisation.*

**Context / Background**
**Detailed Description:** Document and rehearse: how a user returns to a previous version, what happens to data across a downgrade, how a crash report is produced **without any automatic transmission**, and what the maintainer does when a released version is found to be broken. Crash reporting is a local file the user chooses to attach to an issue; nothing is ever sent automatically.

**Scope**
- Rollback procedure, including data compatibility across a downgrade.
- Local crash report generation with a stated location and contents, attached by the user only.
- An incident procedure: how a broken release is communicated given that update delivery is blocked.
- A rehearsal of the rollback on each platform.

**Out of Scope**
- Automatic crash reporting — forbidden.
- Anything depending on update delivery — blocked.

**Acceptance Criteria**
- **Acceptance Criteria:** The rollback procedure is documented and rehearsed on each platform. Data compatibility across a downgrade is stated, including where it is not possible. A crash produces a local report at a stated location containing no content from the user's corpus and nothing is transmitted. The incident procedure names how users would learn of a broken release given the blocked update mechanism.
- **Edge Cases:** A downgrade across a migration that is not reversible — stated plainly, with the backup as the only path back. A crash report containing a filename or a question — the report must exclude corpus content, and a test asserts it. An incident with no way to notify users — acknowledged as a real limitation created by the blocked decision, and named as such rather than glossed over.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §7 report a problem.
- **Validation Rules:** No crash report is transmitted, ever, automatically or otherwise, without the user attaching it themselves.
- **Audit / Logging Requirements:** A crash is logged locally.
- **Analytics Events:** None. Crash reporting that phones home is a constraint violation, not a feature.

**Real-World Example Scenarios**
- A release breaks ingestion on one platform; the maintainer follows the written rollback procedure and users who report the problem are given a working path within an hour.

**Dependencies & Assumptions**
- **Dependencies:** M7-PACK-DEPLOY-142, M7-BACKUP-BE-158, M7-DOC-DOC-164.
- **API / Data Touchpoints:** Log paths; version.
- **Assumptions:** **The blocked update decision directly limits incident response**, and this ticket documents that limitation rather than working around it.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** On each platform, install the current release, use it enough to have data, then follow the written rollback procedure to the previous version. Confirm the product starts, the data is intact or the documented limitation applies, and that a person following only the written procedure could do it. Then induce a crash and confirm a local report is produced at the stated location, contains no corpus content, and is not sent anywhere.
- **Other scenarios:** Inspect a crash report for any filename or question text — there must be none.
- **Known gaps:** There is no way to notify users of a broken release while update delivery is blocked, and that is stated in the procedure.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:6`, documentation, deployment, `constraint:local-first`
- **Granularity:** One procedure, one report format, one rehearsal.

---

### M7-SEC-TEST-166 — Security review before public release

**Type:** Task

**User Story**
- **Actor:** the maintainer publishing a product whose claim is privacy.
- **User Need:** a deliberate review of the surfaces that carry that claim.
- **Business Value:** the source being auditable is the product's strongest argument, and shipping an obvious hole would undo it entirely.
- *As someone publishing a privacy product to an audience that will audit it, I want a deliberate review first, so that the first finding is mine rather than theirs.*

**Context / Background**
**Detailed Description:** A structured review covering each constraint's enforcement point: egress default-deny and the counter's honesty, sandbox isolation and its hostile fixtures, SQL validation and the independent read-only role, the citation and abstention paths, the audit chain and its grants, the injection boundary, and secret handling. Findings are recorded and either fixed or documented as accepted residual risk.

**Scope**
- Review against each of the eight constraints and its enforcement point.
- Dependency vulnerability review across both sides.
- Findings recorded with a fix or an accepted-risk statement.
- Verification that the residual risks the documentation claims to state are actually stated.

**Out of Scope**
- External penetration testing.

**Acceptance Criteria**
- **Acceptance Criteria:** Every constraint has a recorded review result naming where it is enforced and how that was verified. Dependency vulnerabilities are reviewed and either fixed or accepted with a reason. Residual risks — particularly prompt injection — are documented honestly rather than overclaimed. Findings are recorded before release.
- **Edge Cases:** A finding that cannot be fixed before release — documented as an accepted risk with its reasoning, not silently deferred. A dependency vulnerability with no fix available — assessed for actual reachability rather than reacted to by severity alone. A constraint whose enforcement point turns out to be a convention rather than a mechanism — that is a release blocker, since the entire design principle is that a rule with no enforcement point is a wish.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None.
- **Validation Rules:** Each constraint must have a mechanical enforcement point, not a convention.
- **Audit / Logging Requirements:** Review results are recorded with the release.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- The review finds that one code path builds a query without going through the parser, which is the exact class of bug the review exists to find.

**Dependencies & Assumptions**
- **Dependencies:** M7-OFFLINE-TEST-145, M4-DUMP-SEC-091, M4-EVAL-TEST-112.
- **API / Data Touchpoints:** All enforcement points.
- **Assumptions:** A single-maintainer review is not equivalent to external testing, and the documentation says so rather than implying more assurance than exists.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Work through each constraint in a running installation. For egress, attempt an outbound request from every container. For the sandbox, run the hostile fixtures. For SQL, attempt each forbidden statement shape and separately attempt a write as the query role. For citations, run the uncited-claim check. For abstention, run its subset. For audit, alter a record and verify. For injection, add a document with an injection attempt and confirm the flag. For secrets, grep the logs and the repository. Record each result.
- **Other scenarios:** Review the documentation's residual-risk statements and confirm they are present and honest.
- **Known gaps:** No external penetration testing. The injection mitigation is partial and documented as such.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:6`, security, test
- **Granularity:** Eight constraints reviewed against their enforcement points. Upper bound.

---

### M7-PERF-TEST-167 — Measure the performance budgets on a real corpus

**Type:** Task

**User Story**
- **Actor:** the maintainer deciding whether the product is fast enough to ship.
- **User Need:** the stated budgets measured on a realistic corpus, not a fixture.
- **Business Value:** below twenty seconds the product competes with opening the file yourself; above it, people stop.
- *As someone about to publish, I want the answer latency measured on a realistic corpus, so that the budgets are met rather than assumed.*

**Context / Background**
**Detailed Description:** Measure the stated budgets on a corpus of a realistic size: first step label within 400 milliseconds of submitting, first answer token within 3 seconds on standard, full answer median under 20 seconds and ninety-fifth percentile under 60. Also measure ingestion throughput so the queue estimates shown to users are honest. Report per profile with a per-stage breakdown.

**Scope**
- A realistic corpus fixture, larger than the eval fixture.
- Latency measurement for the four answer budgets, per profile.
- Ingestion throughput measurement feeding the queue estimate.
- Recorded results per release.

**Out of Scope**
- Optimisation, which follows from findings.

**Acceptance Criteria**
- **Acceptance Criteria:** The four answer budgets are measured per profile with median and ninety-fifth percentile and a per-stage breakdown. Ingestion throughput is measured and feeds the queue estimate shown to users. Results are recorded per release. A missed budget names the stage responsible.
- **Edge Cases:** A corpus large enough that retrieval dominates — that is the finding, and it changes where optimisation goes. Cold start versus warm — reported separately, because the user experiences both. A profile the test machine cannot run — reported as not measured, never as a pass.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §7 performance budgets.
- **Validation Rules:** Budgets are measured, not asserted.
- **Audit / Logging Requirements:** Results recorded with the release.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- On a 200,000-chunk corpus the reranker turns out to dominate latency, which is the evidence for reducing the candidate window on the standard profile.

**Dependencies & Assumptions**
- **Dependencies:** M5-LOOP-BE-117, M1-ASK-RET-036.
- **API / Data Touchpoints:** The answer path; the trace timings.
- **Assumptions:** The trace's stored timings are accurate enough to serve as the measurement instrument, which avoids a second one.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ingest the realistic corpus through the normal add flow and time it, comparing the actual duration against the estimate the product showed. Then run the latency measurement over a set of questions, discarding nothing and reporting cold and warm separately. Read the per-stage breakdown. Finally ask a question by hand and confirm the felt experience matches.
- **Other scenarios:** Repeat on a light profile and record the honest result.
- **Known gaps:** One machine per profile. Optimisation is out of scope here.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:6`, test, performance
- **Granularity:** One corpus and two measurements.

---

### M7-QA-TEST-168 — Release readiness checklist and the manual regression walkthrough

**Type:** Story

**User Story**
- **Actor:** the maintainer at the point of release.
- **User Need:** one checklist that covers everything that must be true.
- **Business Value:** acceptance is a manual walkthrough from a cold start, not a green test suite — passing tests means the code is well-formed, not that it does anything.
- *As the only person who can say this is ready, I want one checklist that walks the whole product, so that readiness is demonstrated rather than believed.*

**Context / Background**
**Detailed Description:** A single release checklist gathering every gate: the eval suite against its seven categories and their bars, the cable-unplugged test, the tested restore, the security review, the performance measurement, the licence and notices check, the support boundary, the version and changelog, and a full manual regression walkthrough from a cold install through every milestone's headline path. A failure anywhere blocks the release.

**Scope**
- The checklist covering every gate with its pass condition and where its evidence lives.
- A manual regression walkthrough script covering the headline path of every milestone.
- A recorded result per release with evidence attached.

**Out of Scope**
- Automating the manual walkthrough — the point is that a person uses the product.

**Acceptance Criteria**
- **Acceptance Criteria:** The checklist covers every gate with a pass condition. The manual walkthrough covers every milestone's headline path from a cold install. A failure blocks the release. The result and its evidence are recorded per release.
- **Edge Cases:** A gate that cannot be run this release, such as an unavailable eval runner — the release is blocked rather than proceeding unmeasured. A known issue accepted for release — recorded with its reasoning and its follow-up, never silently carried. A walkthrough step that fails intermittently — treated as a failure, since intermittent for the maintainer is constant for someone.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** Exercises every screen in `../ux/`.
- **Validation Rules:** Every gate must pass or be explicitly accepted with reasoning.
- **Audit / Logging Requirements:** The release record holds the results.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A release is held because the abstention subset dropped below its bar, which is exactly what the bar is for.

**Dependencies & Assumptions**
- **Dependencies:** M7-OFFLINE-TEST-145, M7-BACKUP-TEST-159, M7-SEC-TEST-166, M7-PERF-TEST-167, M7-DOC-DOC-163, M7-DOC-DOC-164, M5-EVAL-TEST-124.
- **API / Data Touchpoints:** The whole product.
- **Assumptions:** A single maintainer can execute this in a working day or two; if it grows beyond that it needs splitting, and that is stated.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** This ticket is the walkthrough. On a clean machine, install from the release artefact. Complete first run offline with a manually placed model. Nominate a folder, add a PDF and a scan, watch them index, ask a question and get a cited answer, click the citation and land on the page. Rename the file and confirm the moved state. Ask an uncovered question and read the abstention. Import a CSV and a dump, answer their clarifications, ask a data question and read the query. Correct a memory fact from inside an answer. Ask a question needing both a document and the database, and read the trace. Ask by voice and stop mid-answer. Take a backup, restore it on a second machine, and verify. Export everything and read the files. Run verify on the log. Confirm the outbound count is zero throughout.
- **Other scenarios:** Repeat the walkthrough on each supported platform, or record which platforms were covered.
- **Known gaps:** The walkthrough is long and manual; that is deliberate.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:6`, test, documentation
- **Granularity:** One checklist and one script. Upper bound; executing it is separate from writing it and takes longer.
