# M0 — It runs

**Goal:** Askwell starts on a clean machine and says it is ready. The container stack comes up, the native inference process comes up, the database has its full v1 schema with its invariants, egress is default-deny and counted, and the shell renders with a working local session.

**Phase:** 0 (`../build-plan.md`) · **Depends on:** nothing · **Tickets:** 20 · **Estimated:** 56–81 hours

**Exit condition:** From a clean clone on a machine with only Podman and the platform's package manager, the stack comes up, the shell loads in a browser at localhost, the health surface reports every component individually, the assistant reports itself available, an attempt by any container to reach the internet is refused and counted, and lint, typecheck and tests pass in CI on push.

## Included epics

| Epic | Code | Covers |
| ---- | ---- | ------ |
| Repository and toolchain foundation | `FOUND` | Images, scaffolds, tests, CI, secrets, versioning |
| Container stack and egress control | `STACK` | Compose topology, egress proxy, localhost binding |
| Database and schema groundwork | `DATA` | Migrations, invariants, audit stores |
| Application shell and session | `SHELL` | Local session, navigation, health |
| Native inference process | `MODEL` | Provisioning, supervision, client, failure separation |

---

### M0-FOUND-DEPLOY-001 — Pin Python 3.12 in the API image with the toolchain inside it

**Type:** Task

**User Story**
- **Actor:** the maintainer preparing a machine to work on Askwell.
- **User Need:** a build environment that does not depend on whatever Python the host happens to carry.
- **Business Value:** the host needs only Podman; contributors do not hit unbuildable wheels on day one.
- *As someone setting up Askwell on a machine running a newer Python than the project targets, I want the toolchain to live inside the image, so that my host Python is irrelevant.*

**Context / Background**
**Detailed Description:** The project targets Python 3.12 while the current development machine runs 3.14, and the AI toolchain — inference bindings, OCR, embeddings — has no wheels for 3.14. The API image pins 3.12 and carries the dependency resolver, linter, type checker and test runner inside it, so nothing must be installed on the host. Dependency resolution and locking use `uv`; lint and format use `ruff`; typing uses `mypy` in strict mode over the application source; tests use `pytest`.

**Scope**
- API container image pinned to Python 3.12.
- Dependency manifest and lockfile, with the version read from the repository's `VERSION` file rather than declared separately.
- Linter, formatter, type checker and test runner installed inside the image and runnable against the mounted source.
- A developer entry point that runs each of those inside the container.

**Out of Scope**
- Frontend toolchain (M0-FOUND-FE-003).
- CI wiring (M0-FOUND-DEPLOY-006).
- Any application code beyond what the image needs to start.

**Acceptance Criteria**
- **Acceptance Criteria:** The image builds from a clean clone. Lint, format check, typecheck and tests each run inside the container against mounted source and report results. The declared Python version inside the image is 3.12. The package version resolves to the value in `VERSION`.
- **Edge Cases:** Host has no Python at all — everything still works. Host has an incompatible Python — it is never invoked. Build run with no network available after the first build — cached layers are reused rather than re-resolved.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** No user-facing surface.
- **Validation Rules:** The build fails loudly if the interpreter version inside the image is not 3.12. A version declared in two places is a build failure, not a warning.
- **Audit / Logging Requirements:** None — this is build tooling, not runtime behaviour.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A contributor on a distribution shipping Python 3.14 clones the repository and runs the tests successfully without creating a virtual environment.
- A dependency that has no 3.14 wheel installs cleanly because resolution happens inside the pinned image.

**Dependencies & Assumptions**
- **Dependencies:** None.
- **API / Data Touchpoints:** None.
- **Assumptions:** Podman is present on the host; `podman compose` is the invocation, not `podman-compose`.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** On a machine that has never built this project, clone the repository, build the API image, and run the lint, typecheck and test entry points. Observe each reports a result rather than an interpreter error. Confirm the host's own Python was never used by checking that removing it from the path changes nothing.
- **Other scenarios:** Delete the lockfile and rebuild — the build fails with a clear message rather than silently resolving new versions.
- **Known gaps:** No application code exists to lint or test meaningfully yet; the first real tests arrive in M0-FOUND-TEST-005. No frontend tooling.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:0`, deployment, toolchain
- **Granularity:** One image and four entry points; no application behaviour. Small because it decides nothing about the product.

---

### M0-FOUND-BE-002 — Scaffold the API application with configuration and structured logging

**Type:** Story

**User Story**
- **Actor:** someone who has just started Askwell and wants to know whether it is working.
- **User Need:** a running backend that reports its own state honestly.
- **Business Value:** every later ticket has somewhere to attach; failures are diagnosable from the first day.
- *As someone starting Askwell for the first time, I want it to tell me plainly whether it came up, so that I am not guessing at a blank window.*

**Context / Background**
**Detailed Description:** The API is the only reachable service and it also serves the built frontend. This ticket creates the application, its configuration layer, its structured logging, and a health surface that reports each component separately rather than one aggregate boolean. Configuration is read from environment variables with typed validation at boundaries; logging is structured and machine-readable with no direct console printing anywhere in the codebase. Model names never appear in code — they are configuration values selected by deployment profile.

**Scope**
- Application entry point, typed settings loaded from environment.
- Structured logging with a consistent event shape and no unstructured printing.
- A health surface reporting database, queue, worker, inference process and egress proxy independently, each with a state and a reason when unhealthy.
- Error handling that fails loudly in development and degrades with a stated reason otherwise.

**Out of Scope**
- Session handling (M0-SHELL-SESS-015).
- Serving frontend assets (M0-FOUND-DEPLOY-004).
- Any domain behaviour.

**Acceptance Criteria**
- **Acceptance Criteria:** The application starts with valid configuration and refuses to start with invalid configuration, naming the offending value. The health surface reports each component separately. Logs are structured, include a timestamp and event name, and contain no secrets.
- **Edge Cases:** A required environment variable is absent — startup fails naming it, rather than failing later at first use. The database is up but the inference process is not — health reports exactly that split. Every dependency is down — health still responds rather than hanging.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** Consumed by the shell's ready/not-ready state (M0-SHELL-FE-016) and by the "assistant is unavailable" state in `../states-and-edge-cases.md` §1.
- **Validation Rules:** All configuration is typed and validated at load. Unknown configuration keys are reported rather than ignored.
- **Audit / Logging Requirements:** Startup and shutdown are logged with the resolved profile and component states. No audit record — this is not a user decision.
- **Analytics Events:** Local usage counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- The user's machine restarts, Postgres comes up slowly, and the health surface shows the database as starting rather than the whole product as broken.
- A misspelled environment variable name produces a startup message naming it, instead of a stack trace an hour later.

**Dependencies & Assumptions**
- **Dependencies:** M0-FOUND-DEPLOY-001.
- **API / Data Touchpoints:** Health surface; configuration store is environment only at this stage, with the `settings` table arriving in M0-DATA-DB-012.
- **Assumptions:** Component health is polled cheaply enough to be called on every shell load.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Bring the stack up from cold, open the browser at the local address, and observe the health surface reporting each component. Stop the database container, refresh, and observe only the database reported unhealthy with a reason while the rest still report their state.
- **Other scenarios:** Remove a required environment variable and restart — startup fails with the variable named.
- **Known gaps:** Nothing is authenticated yet. No frontend is served yet. Health has no history and no persistence.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:0`, backend, observability
- **Granularity:** One application skeleton plus one surface. Splitting further would leave a process that starts and reports nothing.

---

### M0-FOUND-FE-003 — Scaffold the frontend as one pinned verified set

**Type:** Task

**User Story**
- **Actor:** the maintainer starting the interface.
- **User Need:** a frontend toolchain whose versions are verified together rather than chosen individually.
- **Business Value:** the component library tracks a framework and styling pairing, not a version range; picking them separately produces a broken first commit.
- *As someone scaffolding the interface, I want the framework, runtime, styling and component library pinned as one verified set, so that the first commit is not immediately contradicted.*

**Context / Background**
**Detailed Description:** The frontend is Next.js 16 with React 19, Tailwind 4 and shadcn/ui, managed with pnpm, and built to static assets. There is no permanent Node process on the user's machine — no server, no session to protect, no search indexing to serve. This ticket scaffolds the project, pins the four as one verified working set, sets TypeScript to strict, and establishes the design tokens from `../ux/design-system.md` §2 and §3 as the styling foundation, including the rule that no web fonts are fetched.

**Scope**
- Project scaffold with the four dependencies pinned as one set, using pnpm.
- Strict TypeScript, no implicit permissive typing.
- Design tokens for colour and type from the design system, with both light and dark values.
- Bundled or system fonts only; no external font or asset requests anywhere.
- A static export build producing assets on disk.

**Out of Scope**
- Any screen (M0-SHELL-FE-016 provides only the shell).
- Serving the assets (M0-FOUND-DEPLOY-004).
- Component work for specific screens.

**Acceptance Criteria**
- **Acceptance Criteria:** The build produces static assets. The four dependencies are pinned to exact versions recorded together. Type checking passes in strict mode. The design tokens are defined once and referenced, not repeated.
- **Edge Cases:** Build run with no network after install — succeeds. A stylesheet or script referencing an external host — the build fails or is caught by the check in M0-STACK-SEC-009's release test.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None yet; tokens back every state in `../ux/design-system.md`.
- **Validation Rules:** No external URL may appear in built output. Colour values appear only as tokens.
- **Audit / Logging Requirements:** None.
- **Analytics Events:** None. There is no analytics SDK and there will not be one (`../success-metrics.md` §6).

**Real-World Example Scenarios**
- A user runs Askwell on a machine with no internet connection and the interface renders with correct fonts and colours.

**Dependencies & Assumptions**
- **Dependencies:** None.
- **API / Data Touchpoints:** None yet.
- **Assumptions:** pnpm is available in the build environment; the static export path is compatible with every screen planned, including the source viewer.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** From a clean clone, install and build the frontend, then open the produced index file directly in a browser with the network disabled. Observe it renders with the intended typeface and background rather than falling back to a default sans-serif on a white page.
- **Other scenarios:** Inspect the built output for any external host reference — there must be none.
- **Known gaps:** No routes, no data, no components beyond the token demonstration. Nothing is served by the API yet.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:0`, frontend, `constraint:local-first`
- **Granularity:** At the upper bound because verifying four versions work together is the actual work. Cannot split without leaving a half-pinned set.

---

### M0-FOUND-DEPLOY-004 — Serve the built frontend assets from the API

**Type:** Task

**User Story**
- **Actor:** someone opening Askwell in their browser.
- **User Need:** one address that serves the whole product.
- **Business Value:** removes a container from a laptop that is also running the user's browser and everything else.
- *As someone running Askwell on my own laptop, I want one process serving the interface, so that there is one thing to start and one thing that can be wrong.*

**Context / Background**
**Detailed Description:** The frontend is built to static assets and served by the API container. This removes the `web` container from the topology. The API serves the assets, falls through to the application entry point for client-side routes, and sets caching that does not strand a user on a stale build after an update.

**Scope**
- Static asset serving from the API, including client-side route fallback.
- Cache behaviour that invalidates on a new build.
- A build step that places assets where the API expects them.

**Out of Scope**
- Frontend content (M0-SHELL-FE-016).
- Update delivery (blocked, M7).

**Acceptance Criteria**
- **Acceptance Criteria:** Opening the local address in a browser loads the interface. A deep client-side route loads directly rather than returning not-found. After a rebuild, a reload serves the new assets rather than a cached old bundle.
- **Edge Cases:** Assets missing entirely — the API reports a clear message naming the missing build rather than serving a blank page. A request for a path that is neither an asset nor a known route — a clear not-found, not the application shell.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** The unbuilt-assets case surfaces as the not-ready state in M0-SHELL-FE-016.
- **Validation Rules:** No asset path may escape the asset directory.
- **Audit / Logging Requirements:** None.
- **Analytics Events:** Local usage counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- The user bookmarks the library screen and opens it directly the next morning; it loads rather than returning not-found.

**Dependencies & Assumptions**
- **Dependencies:** M0-FOUND-BE-002, M0-FOUND-FE-003.
- **API / Data Touchpoints:** Static asset routes.
- **Assumptions:** Every screen in `../ux/` can be served this way; none requires server-side rendering.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Bring the stack up cold, open the local address, and see the interface. Navigate to another route, copy the address, close the browser, reopen and paste it — the same screen loads.
- **Other scenarios:** Rebuild the frontend with a visible change and reload — the change appears without clearing the browser cache manually.
- **Known gaps:** There is only a shell to serve. No offline caching strategy beyond the browser default.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:0`, deployment, frontend
- **Granularity:** One serving concern. Small and self-contained.

---

### M0-FOUND-TEST-005 — Establish the test harness and the first meaningful tests

**Type:** Task

**User Story**
- **Actor:** the maintainer about to write retrieval and SQL validation.
- **User Need:** a test harness that exists before the code that most needs it.
- **Business Value:** retrieval, SQL validation and the agent loop are where correctness cannot be eyeballed; the harness must precede them.
- *As someone about to build the parts that cannot be checked by looking, I want the test harness ready first, so that tests accompany the code rather than trailing it.*

**Context / Background**
**Detailed Description:** Set up the test runner inside the API image with database fixtures that create and tear down a real Postgres schema, async test support, and a convention for where tests live. The first tests cover configuration validation, the health surface's component-by-component reporting, and the migration applying cleanly to an empty database. Tests must run without network access.

**Scope**
- Test runner configuration, fixtures for a disposable database, async test support.
- Tests for configuration failure modes, health reporting and migration application.
- A documented convention for test placement and naming.

**Out of Scope**
- The eval suite (M2-EVAL-TEST tickets).
- Frontend tests.
- Coverage thresholds.

**Acceptance Criteria**
- **Acceptance Criteria:** Tests run inside the container against a disposable database and pass. A deliberately broken configuration produces a failing test rather than a passing one. Tests run with no network available.
- **Edge Cases:** Test database left over from a previous run — the fixture recreates rather than reusing dirty state. Two test runs in parallel — they do not collide on the same database.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None.
- **Validation Rules:** A test that requires network access fails by design rather than being skipped silently.
- **Audit / Logging Requirements:** None.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A contributor changes the health surface and a test catches that a component stopped being reported individually.

**Dependencies & Assumptions**
- **Dependencies:** M0-FOUND-DEPLOY-001, M0-FOUND-BE-002, M0-DATA-DB-012.
- **API / Data Touchpoints:** Disposable database schema.
- **Assumptions:** A real Postgres is used rather than an in-memory substitute, because the schema relies on vector and full-text features a substitute does not have.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** From a clean clone, bring the stack up and run the test entry point. Observe tests discovered, executed and reported. Disconnect the network and run again — the same result.
- **Other scenarios:** Break a configuration default deliberately and confirm the relevant test fails.
- **Known gaps:** No frontend tests, no eval suite, no coverage measurement. Nothing tests retrieval, because retrieval does not exist.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:0`, test
- **Granularity:** Harness plus three narrow tests. Small deliberately — the harness matters more than the coverage at this point.

---

### M0-FOUND-DEPLOY-006 — Continuous integration for lint, typecheck and tests

**Type:** Task

**User Story**
- **Actor:** the maintainer pushing a branch.
- **User Need:** the well-formedness checks running without being remembered.
- **Business Value:** a single maintainer cannot be the check that always runs.
- *As the only person working on this, I want the mechanical checks to run on every push, so that my attention goes to whether it works rather than whether it compiles.*

**Context / Background**
**Detailed Description:** GitHub Actions runs lint, format check, typecheck and the test suite on every push and pull request, using the same pinned API image so results match local runs. The frontend build and type check run in the same workflow. The eval gate is deliberately not here — it needs a model and a longer runner, and it arrives in M2.

**Scope**
- Workflow running backend lint, format check, typecheck and tests.
- Workflow running frontend typecheck and build.
- Caching that does not mask a broken lockfile.

**Out of Scope**
- The eval gate (M2-EVAL-TEST-XXX).
- Release automation, packaging or publishing.

**Acceptance Criteria**
- **Acceptance Criteria:** A push runs the workflow. A lint failure, a type error, a failing test or a failing frontend build each fail the run with a readable reason. The workflow uses the same pinned image as local development.
- **Edge Cases:** A pull request from a branch with a changed lockfile — resolution is not silently skipped by cache. A workflow run with no changes to a given area still runs the whole suite; this is a single-maintainer project and selective running hides breakage.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None.
- **Validation Rules:** No secret is used or required by this workflow.
- **Audit / Logging Requirements:** None.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A commit that typechecks locally but relies on an uncommitted file fails CI, which is exactly when it should be found.

**Dependencies & Assumptions**
- **Dependencies:** M0-FOUND-DEPLOY-001, M0-FOUND-FE-003, M0-FOUND-TEST-005.
- **API / Data Touchpoints:** None.
- **Assumptions:** Hosted runners are adequate for everything except the eval gate.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Push a branch containing a deliberate type error and observe the run fail naming the file and line. Fix it, push again, observe it pass. Confirm the run took a reasonable time on a cold cache.
- **Other scenarios:** Push a branch with a formatting violation only — the run fails on format, distinctly from lint.
- **Known gaps:** No eval gate, no packaging, no release job, no security scanning yet.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:0`, deployment, test
- **Granularity:** One workflow file and its verification. Small.

---

### M0-FOUND-SEC-007 — Secrets as environment variables, with the example file kept current

**Type:** Task

**User Story**
- **Actor:** someone configuring Askwell for the first time.
- **User Need:** to know which values must be supplied without reading the source.
- **Business Value:** a committed connection string is a breach, not a bug (C8).
- *As someone setting Askwell up, I want every value it needs listed in one example file, so that I am not discovering a missing variable at first use.*

**Context / Background**
**Detailed Description:** Every secret and every environment-specific value is an environment variable, never committed. An example file lists every variable with a description and a safe placeholder, and it is updated in the same change that introduces a variable. Ignore rules prevent the real file being committed. Logs must never contain secret values.

**Scope**
- Example environment file covering every variable currently used.
- Ignore rules covering real environment files and any generated credential material.
- A check that fails if a variable is read by the application but absent from the example file.
- Log redaction for values marked secret.

**Out of Scope**
- Passphrase-derived encryption of stored credentials (M4).
- Key management for the online service (M8).

**Acceptance Criteria**
- **Acceptance Criteria:** Every variable the application reads appears in the example file. A variable added without updating the example file fails the check. No secret value appears in any log line. The real environment file cannot be committed.
- **Edge Cases:** A variable used only in a container definition rather than application code — still listed. A value that is a path rather than a secret — listed with a placeholder, not redacted in logs.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None.
- **Validation Rules:** Secret-marked values are redacted in every log path including error reporting.
- **Audit / Logging Requirements:** Configuration changes made through the application later record to the decisions store; environment file edits are outside Askwell and cannot be recorded.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A database password appears in a stack trace during development and is redacted rather than written to the log file.

**Dependencies & Assumptions**
- **Dependencies:** M0-FOUND-BE-002.
- **API / Data Touchpoints:** Configuration loading.
- **Assumptions:** All secret material at this stage is database and queue credentials; user database credentials are stored encrypted in the database, not in the environment (M4).

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Copy the example file, fill it, bring the stack up cold and confirm it starts. Then remove one value and restart — startup names the missing variable.
- **Other scenarios:** Add a new variable in code without updating the example — the check fails.
- **Known gaps:** No encryption at rest yet; no passphrase; the example file is only as complete as the current code.

**Effort & Granularity Check**
- **Estimate:** 1–2 hours · **Priority:** High
- **Labels / Component:** `phase:0`, security
- **Granularity:** One file, one check, one redaction rule. Small.

---

### M0-FOUND-DOC-008 — Version, changelog and release-note discipline

**Type:** Task

**User Story**
- **Actor:** someone reading Askwell's About screen or its repository.
- **User Need:** one version number that means something.
- **Business Value:** a build that ships a number matching nothing is how a support conversation becomes unanswerable.
- *As someone reporting a problem, I want a version number I can quote that identifies exactly what I am running, so that the answer is not "which build is that".*

**Context / Background**
**Detailed Description:** A single manually maintained version value at the repository root is the source of truth. Both the API package and the frontend package read from it rather than declaring their own. Every user-visible change bumps it and adds a changelog entry under the new heading. The About screen (`../ux/settings.md` §7) later renders this value, derived rather than retyped.

**Scope**
- Version file as the single source, read by both packages.
- Changelog structure with a heading per version.
- A check that the two packages agree with the version file.

**Out of Scope**
- Release publishing, tagging or deployment.
- The About screen itself (M7).

**Acceptance Criteria**
- **Acceptance Criteria:** Both packages report the version from the single file. A deliberate mismatch fails the check. The changelog has an entry for the current version.
- **Edge Cases:** A pre-release or build identifier — the format has no fourth component; a build identifier, if one is ever needed, is an always-increasing integer appended after a plus sign.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** Consumed later by `../ux/settings.md` §7.
- **Validation Rules:** Version format is three numeric components only.
- **Audit / Logging Requirements:** The running version is included in the startup log line.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A user pastes the version from the About screen into an issue and the maintainer can identify the exact code.

**Dependencies & Assumptions**
- **Dependencies:** M0-FOUND-DEPLOY-001, M0-FOUND-FE-003.
- **API / Data Touchpoints:** Startup log; later, the About screen.
- **Assumptions:** No build-number scheme is needed until the offline install bundle in M7.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Bring the stack up cold and read the startup log; the version matches the file. Change the file, rebuild, and observe the new value.
- **Other scenarios:** Hand-edit a package version to disagree — the check fails.
- **Known gaps:** No About screen yet, so the version is only visible in logs.

**Effort & Granularity Check**
- **Estimate:** 1–2 hours · **Priority:** Medium
- **Labels / Component:** `phase:0`, documentation
- **Granularity:** One file and one check. Small.

---

### M0-STACK-DEPLOY-009 — Compose stack bringing up API, database, queue and worker

**Type:** Story

**User Story**
- **Actor:** someone installing Askwell on their own machine.
- **User Need:** one command that starts everything and one place to see whether it worked.
- **Business Value:** every container is something a non-technical user must have working unaided.
- *As someone who has never run a container before, I want starting Askwell to be one step, so that installing it is not a systems administration task.*

**Context / Background**
**Detailed Description:** The Compose stack defines the API, PostgreSQL with the vector extension, Redis, and the background worker. It does not yet define the voice, sandbox or egress-proxy services — those arrive in their own tickets and phases. Volumes are named and persist across restarts. Services declare health so that dependents wait rather than crash-looping. The database image is PostgreSQL 18 with pgvector, or 17 if no maintained 18 image with the extension exists at scaffold time.

**Scope**
- Compose definition for API, database, queue and worker with named volumes.
- Health declarations and startup ordering.
- Background job runner wired to the queue and able to execute a trivial job.

**Out of Scope**
- Egress proxy (M0-STACK-SEC-010), sandbox database (M4), voice (M6).
- Installer and supervision (M7).

**Acceptance Criteria**
- **Acceptance Criteria:** One command brings the stack up from a clean clone. The database retains data across a stop and start. The worker picks up and completes a trivial enqueued job. Health declarations prevent the API reporting ready before the database accepts connections.
- **Edge Cases:** Port already in use — the failure names the port. Volume from an older schema version present — migrations run and either succeed or fail with a readable message. The machine restarts mid-job — the job is retried rather than lost.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** Feeds the ready/not-ready state in M0-SHELL-FE-016 and the "model not loaded" split in `../states-and-edge-cases.md` §1.
- **Validation Rules:** No service binds to a network-reachable interface except through the deliberate localhost binding in M0-STACK-SEC-012.
- **Audit / Logging Requirements:** Each service logs start and stop with its version.
- **Analytics Events:** Local usage counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- The user closes their laptop lid, reopens it the next day, and their sources and conversations are still there.

**Dependencies & Assumptions**
- **Dependencies:** M0-FOUND-DEPLOY-001, M0-FOUND-BE-002.
- **API / Data Touchpoints:** Database and queue connections.
- **Assumptions:** `podman compose` through the external Compose provider is the supported invocation; a Docker daemon is never assumed.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** From a clean clone with no images built, run the bring-up command. Wait, then open the local address and confirm the shell loads and health reports every defined service. Stop the stack, start it again, and confirm data written before the stop is still present.
- **Other scenarios:** Occupy the API port with another process and bring the stack up — the error names the port.
- **Known gaps:** Inference, voice, sandbox and egress services are not in the stack yet. There is no installer; this is a developer bring-up.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:0`, deployment
- **Granularity:** Four services and their volumes. At the upper bound; splitting would leave a stack that cannot come up.

---

### M0-STACK-SEC-010 — Default-deny egress proxy with every service routed through it

**Type:** Story

**User Story**
- **Actor:** a lawyer whose entire reason for installing Askwell is that nothing leaves the machine.
- **User Need:** the local-only promise enforced structurally, not by convention.
- **Business Value:** C1 is the reason the product can exist for its users; an unexpected runtime request breaks the only promise that matters.
- *As someone whose client files cannot leave this laptop, I want outbound traffic blocked by the network itself, so that a dependency making an unexpected call cannot quietly break the promise.*

**Context / Background**
**Detailed Description:** Every container routes outbound traffic through a default-deny proxy; nothing else has a route out. In local mode the proxy permits nothing. Application-level enforcement was rejected because the realistic threat is a dependency making an unexpected call, not deliberate code. Network policy alone was rejected because nothing in that path can count a request that was refused, and the settings screen promises a measured count. The sandbox database, when it arrives in M4, has no route to the proxy at all.

**Scope**
- Egress proxy service in the stack, default-deny, with no allowed destinations in local mode.
- Network configuration such that no other container has a direct route out.
- Refusal logging with destination and originating service.
- Documentation of how a destination would be authorised, without authorising any.

**Out of Scope**
- The refused-request counter surface (M0-STACK-SEC-011).
- Per-conversation online authorisation (M8, blocked on pricing for the surrounding feature but the mechanism is designed here).
- The cable-unplugged release test (M7).

**Acceptance Criteria**
- **Acceptance Criteria:** A deliberate outbound request from the API, worker or database container is refused. The refusal is logged with the destination and the service that attempted it. No container can reach the internet by bypassing the proxy. **C1 is preserved because the deny is the default state and requires a positive authorisation to change, per conversation.**
- **Edge Cases:** DNS resolution attempts are refused as well as connections, since a resolution alone leaks a hostname. A container attempting a direct address rather than a hostname is still refused. The proxy itself being down must not silently open a route.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §4 states network activity as a fact rather than a toggle. `../states-and-edge-cases.md` §1 forbids rendering an offline warning — being offline is the design point, not a degraded state.
- **Validation Rules:** No allowed destination may be configured statically. Authorisation is per conversation and time-bound.
- **Audit / Logging Requirements:** Every refusal is logged. Authorisations, when they exist, are decisions-store records.
- **Analytics Events:** Local counter of refusals only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A transitive dependency tries to check for its own updates on import; the request is refused and logged, and the user sees the count is not zero and can ask why.

**Dependencies & Assumptions**
- **Dependencies:** M0-STACK-DEPLOY-009.
- **API / Data Touchpoints:** Refusal log consumed by M0-STACK-SEC-011.
- **Assumptions:** The native inference process, being outside the container network, is covered separately by the release test in M7 and by never being configured with a remote endpoint.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Bring the stack up cold. From inside the API container, attempt to fetch a well-known public address. Observe the attempt fails. Check the proxy log and see the destination recorded. Repeat from the worker container with the same result.
- **Other scenarios:** Attempt a raw address rather than a hostname — also refused. Stop the proxy and repeat — the request still fails rather than succeeding.
- **Known gaps:** No user-visible counter yet. The native inference process is not behind the proxy and is covered by the release test instead. Online authorisation is not implemented.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:0`, security, `constraint:local-first`
- **Granularity:** One service and the network topology around it. Upper bound because the network configuration is the work; splitting leaves a proxy nothing routes through.

---

### M0-STACK-SEC-011 — Expose the refused-outbound-request count to the application

**Type:** Story

**User Story**
- **Actor:** a suspicious user reading the privacy section of settings.
- **User Need:** a number that is measured rather than asserted.
- **Business Value:** the settings screen promises a live count as the proof of C1; a count the application produces about itself is exactly the "trust us" this product refuses elsewhere.
- *As someone who does not take a privacy claim on faith, I want to see a count produced by the thing doing the blocking, so that the zero means something.*

**Context / Background**
**Detailed Description:** The proxy counts requests it refused and requests it permitted. The API reads those counters from the proxy and exposes them for the settings screen. The number shown to the user is the proxy's, not the application's. Counters persist across restarts so the figure is cumulative for the install rather than for the current process.

**Scope**
- Counter collection from the proxy: refused, permitted, and last refusal detail.
- Persistence across restarts.
- An API surface returning the counts and the most recent refusals.

**Out of Scope**
- The settings screen rendering (M7-SET-FE tickets).
- Alerting on a non-zero count.

**Acceptance Criteria**
- **Acceptance Criteria:** After a deliberate refused request, the count increases and the destination is retrievable. After a stack restart, the cumulative count is retained. The permitted count is zero in local mode.
- **Edge Cases:** The proxy restarts while the API is running — the API reports the counters as temporarily unavailable rather than reporting zero. A very large number of refusals — the recent-refusals list is capped and says so.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §4 — a statement with a live count, not a toggle.
- **Validation Rules:** The API must not compute or estimate the count; if the proxy cannot be read, the value is unavailable, never zero.
- **Audit / Logging Requirements:** Counter reads are not audited; refusals already are.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- Six months in, the user opens settings, sees zero permitted outbound requests, and that is the whole proof they wanted.

**Dependencies & Assumptions**
- **Dependencies:** M0-STACK-SEC-010.
- **API / Data Touchpoints:** Proxy counters; API read surface.
- **Assumptions:** The proxy can expose counters without itself needing outbound access.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Bring the stack up cold, read the count through the API and observe zero refusals and zero permitted. Trigger a refused request from a container, read again, and observe the refused count at one with the destination visible. Restart the stack and confirm the count is still one.
- **Other scenarios:** Stop the proxy and read the count — unavailable, not zero.
- **Known gaps:** No screen shows this yet. There is no way to authorise a destination, so the permitted count can only ever be zero at this stage.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:0`, security, observability, `constraint:local-first`
- **Granularity:** Read, persist, expose. Small.

---

### M0-STACK-SEC-012 — Bind the API to localhost and prove it is unreachable from the network

**Type:** Task

**User Story**
- **Actor:** someone working from a café.
- **User Need:** their corpus not served to the wireless network they are on.
- **Business Value:** a laptop on shared wifi must not be publishing its owner's confidential material.
- *As someone working on a client's files in a public place, I want Askwell reachable only from my own machine, so that being on an untrusted network is not a disclosure.*

**Context / Background**
**Detailed Description:** The API binds to the loopback interface only, never to all interfaces. This is verified rather than asserted: a check from another host on the same network must fail to connect. No other service is published at all.

**Scope**
- Loopback-only binding for the API's published port.
- No published ports on any other service.
- A documented verification procedure for the release test.

**Acceptance Criteria**
- **Acceptance Criteria:** The API answers from the local machine. A connection attempt from another machine on the same network is refused. No other service is reachable from the host, let alone the network.
- **Edge Cases:** A container runtime that publishes to all interfaces by default — explicitly overridden. A user who deliberately wants network access — out of scope and not offered; there is no configuration for it in v1.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None.
- **Validation Rules:** A binding to all interfaces fails the release checklist.
- **Audit / Logging Requirements:** The bound address is logged at startup.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A colleague on the same office network scans for open ports and finds nothing.

**Dependencies & Assumptions**
- **Dependencies:** M0-STACK-DEPLOY-009.
- **API / Data Touchpoints:** None.
- **Assumptions:** The browser and Askwell always run on the same machine — the topology assumes it.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Bring the stack up cold and open Askwell in the local browser — it loads. From a second machine on the same network, open the first machine's address and port — the connection is refused rather than timing out on a login page.
- **Other scenarios:** Confirm no other service port answers even from the host.
- **Known gaps:** Nothing prevents a user deliberately reconfiguring their own machine to forward the port; that is theirs to do.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** Critical
- **Labels / Component:** `phase:0`, security
- **Granularity:** One binding decision plus its verification. Small.

---

### M0-DATA-DB-013 — First migration creating the v1 schema

**Type:** Story

**User Story**
- **Actor:** the maintainer starting on ingestion.
- **User Need:** the whole data model present from the first migration.
- **Business Value:** retrofitting a column later means a migration on a user's own machine, where there is no operator and no rollback.
- *As someone about to build ingestion, I want the full schema in place from the start, so that adding a field later is not a migration run on somebody's laptop.*

**Context / Background**
**Detailed Description:** Create the schema described in `../architecture.md` §7 through a reversible migration: settings, sources, documents, chunks, schema notes, memory, clarifications, conversations, messages, citations, fact usage, and the two audit tables. There are no organisations, users or roles — those were removed with the repositioning. The vector column dimension follows the embedding model and is read from configuration rather than hardcoded in the migration. Full-text search configuration is set up alongside the vector column, including the Tamil-aware text configuration kept as a hedge rather than a feature.

**Scope**
- Migration creating every table with its columns, keys and indexes.
- Vector column with dimension from configuration; full-text column and index.
- Reversibility verified by applying and rolling back.

**Out of Scope**
- Raw invariants the ORM cannot express (M0-DATA-DB-014).
- Audit hash chaining behaviour (M0-DATA-OBS-015).
- Any application code reading these tables.

**Acceptance Criteria**
- **Acceptance Criteria:** The migration applies to an empty database and rolls back cleanly. Every table in `../architecture.md` §7 exists with the documented columns. No table named for organisations, users or roles exists. The vector dimension matches the configured embedding model.
- **Edge Cases:** Applying twice — the second is a no-op, not an error. Applying against a database without the vector extension — a clear failure naming the missing extension. A configured dimension that disagrees with an existing column — refuse rather than silently truncate.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None.
- **Validation Rules:** Deletion and supersession are distinct columns and must never be conflated.
- **Audit / Logging Requirements:** Migration application is logged with the revision applied.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- Six months later a user upgrades and the migration chain applies cleanly because the first one was reversible and complete.

**Dependencies & Assumptions**
- **Dependencies:** M0-STACK-DEPLOY-009.
- **API / Data Touchpoints:** All tables.
- **Assumptions:** The embedding model produces 1024-dimension vectors; the value is configuration, so a change is a configuration change plus a re-embed, not a schema edit.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** From a clean clone with no volumes, bring the stack up. Observe the migration running in the startup log and the API reaching ready. Stop the stack, remove the volume, start again, and observe the same clean application.
- **Other scenarios:** Roll back to base and re-apply.
- **Known gaps:** No invariants beyond keys yet. No data. Nothing reads these tables.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:0`, database
- **Granularity:** One migration covering twelve tables. Upper bound; splitting the schema across migrations would create a window where the invariants in the next ticket cannot be added.

---

### M0-DATA-DB-014 — Raw invariants in the creating migration

**Type:** Task

**User Story**
- **Actor:** the maintainer relying on the database to catch what code will not.
- **User Need:** the invariants present from the moment the tables exist.
- **Business Value:** a window in which an invariant is unenforced is a window in which bad rows are written and must be cleaned up later on a user's machine.
- *As someone who cannot inspect a user's database, I want the rules enforced by the database itself from the first migration, so that impossible states are impossible rather than merely discouraged.*

**Context / Background**
**Detailed Description:** Add, in the same migration that creates the tables, the constraints the ORM will not express: no update or delete grant on either audit table for the application role; a partial unique index giving one live version per source and content hash where the row is neither deleted nor superseded; a check that a chunk with cleared content has no embedding, so a tombstoned document cannot keep influencing retrieval; a check that a clarification marked answered actually carries an answer; and a citation foreign key that is deliberately not cascade-delete, so a deleted document's chunk row survives for the citation to resolve against.

**Scope**
- All five invariants, in the creating migration.
- A read-only database role, separate from the application role, for later query execution against user data.
- Tests that each invariant rejects the state it exists to prevent.

**Out of Scope**
- Hash chain computation (M0-DATA-OBS-015).
- Tombstone behaviour in the application (M2).

**Acceptance Criteria**
- **Acceptance Criteria:** An attempt to update an audit row fails at the database. Two live versions of the same content in one source cannot both exist. A chunk with cleared content and a non-null embedding is rejected. A clarification marked answered without an answer is rejected. Deleting a document does not cascade to its citations. **C6 is preserved because the append-only guarantee is a grant, not application logic.**
- **Edge Cases:** A superseded document and a deleted document with the same hash coexist — permitted, because the partial index applies only to live rows. A chunk being cleared as part of deletion sets content and embedding in one statement, not two.
- **Permissions / Roles:** Two database roles exist — the application role and an independent read-only role — but no user roles. Not applicable in the product sense.
- **UI States:** None.
- **Validation Rules:** All five invariants as stated.
- **Audit / Logging Requirements:** The grants themselves are the audit guarantee.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A bug in a later deletion path tries to clear content while leaving the embedding; the database refuses and the bug surfaces in development instead of quietly leaving deleted material in search results.

**Dependencies & Assumptions**
- **Dependencies:** M0-DATA-DB-013.
- **API / Data Touchpoints:** Every table carrying an invariant.
- **Assumptions:** The application connects as a role that does not own the audit tables.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Bring the stack up cold. Using the application's own connection, attempt each of the five forbidden states through a test and observe each rejected with a database-level error rather than an application-level one.
- **Other scenarios:** Roll the migration back and forward; the invariants return.
- **Known gaps:** No application code exercises these paths yet. The read-only role has nothing to query until M4.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:0`, database, `constraint:audit`, `constraint:sql-safety`
- **Granularity:** Five invariants and one role. Small because each is a single statement plus a test.

---

### M0-DATA-OBS-015 — Hash-chained audit stores with fail-the-action write semantics

**Type:** Story

**User Story**
- **Actor:** a consultant who may one day need to show a client exactly what was asked of a confidential corpus.
- **User Need:** a record that is verifiable rather than merely asserted.
- **Business Value:** the honest guarantee — the application never rewrites history and manual tampering is detectable — is genuinely useful and is all that is available on a machine the user owns.
- *As someone who might have to account for what I did with a client's files, I want a record whose integrity I can check, so that "here is the log" means something.*

**Context / Background**
**Detailed Description:** Both database-backed audit stores chain each record to the hash of the previous one. Writing a decision or an interaction record is part of the same transaction as the action it records, so a failed audit write fails the action. Traces are a capped file ring buffer and never fail an action. This ticket builds the chaining, the write path and the verification pass; the disk budget staging and the export arrive in M7. **It is tamper-evident, never described as immutable.**

**Scope**
- Hash chain computation and storage on both database-backed stores.
- Transactional write path so an audit failure fails the action.
- Trace ring buffer with a cap, failing open.
- A verification pass that walks a chain and reports the first break by record.

**Out of Scope**
- Disk budget staging (M7).
- Export and the bundled verifier (M7).
- The settings surface for verification (M7).

**Acceptance Criteria**
- **Acceptance Criteria:** Each record stores the previous record's hash and its own. Verification passes on an untouched chain. Verification names the exact record where a manually altered chain breaks. An induced audit write failure causes the recorded action to fail rather than proceed unlogged. A trace write failure never fails an action. **C6 is preserved: append-only by grant, tamper-evident by chain, and the wording avoids "immutable" everywhere it appears.**
- **Edge Cases:** The very first record has no predecessor and must chain to a defined genesis value rather than null-with-special-handling. Two writes racing — the chain must serialise rather than fork. A trace older than the cap is dropped silently and the answer's citations survive, because citations are a real table and do not rotate.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../states-and-edge-cases.md` §6 — a broken chain is reported plainly, naming where; §1 — a decisions-store write failure fails the action with a reason and what to free.
- **Validation Rules:** A record whose computed hash does not match its stored hash is a chain break, not a warning.
- **Audit / Logging Requirements:** This ticket is the audit requirement.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user edits a row directly with a database client out of curiosity; verification later names that record and the user learns the chain works.
- The disk fills while a clarification answer is being saved; the save fails with a clear reason rather than storing a memory fact with no audit record.

**Dependencies & Assumptions**
- **Dependencies:** M0-DATA-DB-013, M0-DATA-DB-014.
- **API / Data Touchpoints:** Both audit tables; trace ring buffer on disk.
- **Assumptions:** The decisions store is measured in kilobytes, which is what makes fail-closed practical rather than a support ticket.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Bring the stack up cold. Perform an action that writes a decision record — changing a setting is enough at this stage. Run the verification pass and observe it reports the chain intact. Alter a record directly in the database, run verification again, and observe it names that record as the break.
- **Other scenarios:** Make the audit table unwritable and repeat the setting change — the change fails with a stated reason and the setting is unchanged.
- **Known gaps:** Nothing writes interaction records yet — there are no questions. No export, no budget enforcement, no verification screen.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:0`, observability, `constraint:audit`
- **Granularity:** Chain, write semantics, ring buffer, verification. Upper bound; splitting leaves a chain nothing verifies.

---

### M0-SHELL-SESS-016 — Local single-user session bound to localhost

**Type:** Story

**User Story**
- **Actor:** the one person using this machine.
- **User Need:** to open Askwell and use it, without an account.
- **Business Value:** there is nothing to sign into; any credential field here would contradict the entire product.
- *As the only person who uses this laptop, I want Askwell to open and work, so that I am not logging into software running on my own machine.*

**Context / Background**
**Detailed Description:** There is one user. They already control the machine, the disk and the database. Authentication is a local session bound to loopback — enough to prevent another process on the machine from casually driving the API, and nothing more. No roles, no multi-factor, no token blacklist, no password. The optional passphrase in M7 is a separate feature about encryption at rest, not about login.

**Scope**
- Session establishment on first load from the local browser.
- Session persistence across restarts of the browser and of the stack.
- Rejection of requests without a valid session.

**Out of Scope**
- Passphrase and encryption at rest (M7).
- Any role or permission concept — there is none.
- Multi-factor, password reset, account recovery.

**Acceptance Criteria**
- **Acceptance Criteria:** Opening Askwell in the local browser establishes a session without any prompt. A request without a session is rejected. The session survives a browser restart and a stack restart. There is no sign-in screen anywhere.
- **Edge Cases:** Two browser windows — both work; there is one user. The session store is cleared — a new session is established silently on the next load, with no prompt. A request from a different origin is rejected.
- **Permissions / Roles:** Single user — no roles. Not applicable. This is the ticket that makes that explicit in code.
- **UI States:** `../ux/first-run.md` §5 — no account, no email, no sign-in.
- **Validation Rules:** Cross-origin requests are refused. Session material is never logged.
- **Audit / Logging Requirements:** Session establishment is logged; it is not a decision record.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- The user reopens their laptop after a week and Askwell is exactly where they left it, with no login.

**Dependencies & Assumptions**
- **Dependencies:** M0-FOUND-BE-002, M0-STACK-SEC-012.
- **API / Data Touchpoints:** Session store; `settings` table.
- **Assumptions:** Loopback binding plus origin checking is proportionate for a single-user local application; anyone with physical access has already won.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** From a cold start, open Askwell in the browser. Observe it loads straight into the product with no prompt for a name, email or password. Close the browser entirely, reopen, and observe it loads again with no prompt. Restart the stack and repeat.
- **Other scenarios:** Issue a request without the session and observe it rejected.
- **Known gaps:** No passphrase, no encryption at rest, no lock screen. Anyone with the machine has the corpus, which is stated deliberately.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:0`, auth/session
- **Granularity:** One session mechanism. Small because almost everything usually in this area is deliberately absent.

---

### M0-SHELL-FE-017 — Application shell, navigation and the ready state

**Type:** Story

**User Story**
- **Actor:** someone who has just started Askwell and wants to see something.
- **User Need:** a window that shows the product exists and reports honestly whether it is ready.
- **Business Value:** the first thirty seconds decide whether a free download survives.
- *As someone who has just installed this, I want the window to tell me what state it is in, so that I know whether to wait or to fix something.*

**Context / Background**
**Detailed Description:** The shell is the three-column layout from `../ux/design-system.md` §4 with the left rail carrying sources, memory and settings, an empty centre and the provenance margin reserved. It renders the component-level ready state from the health surface, distinguishing the container stack being down from the assistant process being down, because those have different fixes.

**Scope**
- Three-column shell with the left rail and reserved margin.
- Route stubs for the screens that arrive later, each rendering its empty state placeholder.
- Ready and not-ready states driven by component health, with a per-component reason.

**Out of Scope**
- Any screen's content beyond a placeholder.
- Keyboard shortcuts beyond basic navigation.

**Acceptance Criteria**
- **Acceptance Criteria:** The shell renders at the local address with the left rail and the reserved margin. When a component is unhealthy, the shell names it and states what still works. When the assistant is unavailable but the database is fine, the shell says the assistant is unavailable rather than that Askwell is down.
- **Edge Cases:** Health cannot be read at all — the shell says so rather than rendering as if healthy. Window narrower than the three-column breakpoint — the margin moves inline rather than disappearing, per `../ux/ask.md` §5.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/design-system.md` §4 for layout; `../states-and-edge-cases.md` §1 for the model-not-loaded and offline states — **never render an offline warning**, because being offline is the design point.
- **Validation Rules:** No screen may hide the provenance margin.
- **Audit / Logging Requirements:** None.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- The user's inference process failed to start after a system update; the shell says the assistant is unavailable and that browsing sources still works, rather than showing a blank product.

**Dependencies & Assumptions**
- **Dependencies:** M0-FOUND-DEPLOY-004, M0-FOUND-FE-003, M0-SHELL-SESS-016, M0-MODEL-BE-020.
- **API / Data Touchpoints:** Health surface.
- **Assumptions:** Every later screen fits this shell; none needs a different chrome.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Bring the stack up cold and open the local address. Observe the shell with its left rail and the reserved margin, and a ready indication. Stop the inference process only and reload — observe the assistant reported unavailable while navigation still works. Stop the database and reload — observe a different, specific message.
- **Other scenarios:** Narrow the window past the breakpoint and confirm the margin moves inline rather than vanishing.
- **Known gaps:** Every screen is a placeholder. No conversation, no sources, no settings content. Offline shows nothing, which is correct.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:0`, frontend
- **Granularity:** Shell and health rendering only. Small because no screen content is included.

---

### M0-MODEL-DEPLOY-018 — Provision and supervise the native inference process

**Type:** Story

**User Story**
- **Actor:** someone on a Mac laptop who expects their machine's acceleration to be used.
- **User Need:** inference that reaches the GPU on their platform.
- **Business Value:** containerised inference would leave the accelerated profiles unreachable on the platform most target users carry.
- *As someone with an accelerated laptop, I want Askwell to use it, so that answers take seconds rather than a minute.*

**Context / Background**
**Detailed Description:** The inference server runs as a native host process, not a container, so GPU acceleration works on Linux, Windows and macOS. This ticket starts it, supervises it, restarts it on unexpected exit with backoff, and reports its state distinctly from the container stack. It serves generation, embeddings and reranking from the same process. Model files are supplied locally and never fetched at runtime.

**Scope**
- Start, stop and supervise the native process on all three platforms.
- Restart with backoff on unexpected exit, with the failure reason retained.
- Report process state, loaded model and acceleration in use.
- Refuse to start if the model file named in configuration is absent, naming the expected path.

**Out of Scope**
- The installer that provisions it on a user's machine (M7).
- Model bundling and manual placement (M7).
- Hardware profile selection (M7).

**Acceptance Criteria**
- **Acceptance Criteria:** The process starts and reports the loaded model and whether acceleration is in use. Killing it externally results in a restart with backoff and a logged reason. A missing model file produces a clear refusal naming the path, not a crash loop. Generation, embedding and reranking are all served by it.
- **Edge Cases:** The process starts but the model fails to load — reported as loading-failed, distinct from not-running. Repeated crash — backoff caps and the state becomes unavailable with the last reason retained rather than restarting forever. Insufficient memory for the configured model — the failure names memory rather than reporting a generic error.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../states-and-edge-cases.md` §1 — "the assistant is unavailable", with a fix path, while document browsing and search continue.
- **Validation Rules:** No model name is hardcoded; all come from configuration selected by profile. No remote endpoint may be configured in local mode.
- **Audit / Logging Requirements:** Process start, stop, model loaded and crash reasons are logged. A deliberate model swap by the user is a decisions record (M7).
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A macOS user's process is killed by memory pressure; Askwell restarts it, and if it fails twice the shell says the assistant is unavailable with the memory reason.

**Dependencies & Assumptions**
- **Dependencies:** M0-FOUND-BE-002, M0-STACK-DEPLOY-009.
- **API / Data Touchpoints:** Process state feeds the health surface.
- **Assumptions:** *Assumption, explicitly accepted:* speech-to-text stays containerised on CPU. If it turns out to need GPU access on accelerated profiles, this supervision work extends to a second native process and the installer changes — flagged in M6-AUDIO-DEPLOY-118.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** On a cold machine, start Askwell and observe the shell report the assistant available and name the loaded model. Kill the inference process from the operating system and watch the shell change to unavailable, then return to available after the restart. Rename the model file and restart — the shell reports the assistant unavailable with the missing path named.
- **Other scenarios:** Configure a model larger than available memory and observe a memory-specific failure.
- **Known gaps:** No installer provisions this yet; it is started by a developer script. No model download, no manual placement flow, no profile selection.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:0`, deployment, `constraint:local-first`
- **Granularity:** Supervision across three platforms is the upper bound. Splitting by platform would leave two platforms unsupported at the end of the milestone.

---

### M0-MODEL-BE-019 — Inference client with model names from configuration only

**Type:** Task

**User Story**
- **Actor:** the maintainer swapping a model for a profile.
- **User Need:** one place that knows model names.
- **Business Value:** a hardcoded model name is how a deployment profile silently stops meaning anything.
- *As someone tuning which model a profile uses, I want to change one configuration value, so that no code change is needed to swap a model.*

**Context / Background**
**Detailed Description:** A single client wraps the native inference process for generation, embedding and reranking. It reads model identifiers from configuration selected by deployment profile, never from literals in code. It handles the process being unavailable by raising a distinct, catchable unavailability rather than a generic error, so callers can degrade to search rather than failing.

**Scope**
- Client for generation, embedding and reranking against the native process.
- Model identifiers resolved from configuration by profile.
- A distinct unavailable condition that callers can handle.
- Timeouts and retry behaviour appropriate to a local process.

**Out of Scope**
- Streaming to the browser (M1).
- The online backend (M8).
- Prompt content — prompts live as versioned files and arrive with the features that use them.

**Acceptance Criteria**
- **Acceptance Criteria:** Generation, embedding and reranking each work through the client. No model name appears as a literal anywhere in application code. When the process is down, callers receive an unavailability they can distinguish from a failure of the request itself.
- **Edge Cases:** The process is up but slow — a timeout that is generous, since a light profile can legitimately take twenty seconds. The process returns a malformed response — surfaced as a failure, not silently coerced.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** Feeds the "assistant unavailable" state in `../ux/ask.md` §5.
- **Validation Rules:** A configured model identifier that the process does not have loaded is a startup-time failure, not a per-request one.
- **Audit / Logging Requirements:** The backend and model in use are recorded on every interaction record from M1 onward.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- Switching a profile from a 4B to an 8B model is a configuration edit and a restart, with no code change.

**Dependencies & Assumptions**
- **Dependencies:** M0-MODEL-DEPLOY-018.
- **API / Data Touchpoints:** Inference process; configuration.
- **Assumptions:** One process serves all three functions; if reranking later needs its own process, this client is the seam.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Bring everything up cold and use a developer diagnostic to request a short generation, an embedding and a rerank, observing each returns. Stop the inference process and repeat — each reports unavailable, distinctly.
- **Other scenarios:** Search the codebase for model name literals; there are none.
- **Known gaps:** No streaming, no prompts, no online backend, no evaluation of output quality.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:0`, backend
- **Granularity:** One client with three functions. Small.

---

### M0-MODEL-BE-020 — Report the two distinct causes of "the assistant is unavailable"

**Type:** Task

**User Story**
- **Actor:** someone whose Askwell stopped answering.
- **User Need:** to know whether the container stack or the assistant process is the problem, because the fixes differ.
- **Business Value:** the accepted cost of native inference is exactly this split; leaving it undiagnosed is how the cost turns into support load.
- *As someone whose questions have stopped working, I want to be told which part failed, so that I try the right fix instead of reinstalling.*

**Context / Background**
**Detailed Description:** Native inference means "the assistant is unavailable" has two causes that look identical to a user: the container stack is not running, or the native process is not running. Each has a different remedy. The health surface and the shell must separate them, name the likely fix, and state what still works in each case.

**Scope**
- Distinct health states for stack-down and assistant-down.
- A stated fix path for each.
- Confirmation in each case of what still works — retrieval and browsing survive an assistant failure.

**Out of Scope**
- Automatic repair.
- The installer's supervision UI (M7).

**Acceptance Criteria**
- **Acceptance Criteria:** With the stack down, the browser cannot reach Askwell at all, and the installer-side supervision surface later covers this; with the stack up and the assistant down, the shell states the assistant is unavailable, names the fix and confirms browsing and search still work.
- **Edge Cases:** Both down — the user sees the stack case, because that is the one they can act on first. The assistant is restarting — reported as restarting, not as failed.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../states-and-edge-cases.md` §1 "Model not loaded"; `../ux/ask.md` §5 "Model unavailable" — degrade to search, not to a blank product.
- **Validation Rules:** The two causes must never be collapsed into one message.
- **Audit / Logging Requirements:** State transitions are logged with the cause.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A Windows user's antivirus quarantines the inference binary; the shell says the assistant is unavailable and names the executable path, and the user finds it in quarantine.

**Dependencies & Assumptions**
- **Dependencies:** M0-MODEL-DEPLOY-018, M0-FOUND-BE-002.
- **API / Data Touchpoints:** Health surface.
- **Assumptions:** The user can act on a named path or a named service; the installer in M7 gives them a button for it.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** From a cold start with everything healthy, stop only the inference process. Reload the browser and read the message — it names the assistant, offers a fix, and says search still works. Restart it, confirm recovery, then stop the whole stack and confirm the failure is visibly different.
- **Other scenarios:** Trigger a restart and confirm the transient restarting state appears.
- **Known gaps:** No repair button yet; the fix is described, not performed.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:0`, observability, frontend
- **Granularity:** Two states and their copy. Small.
