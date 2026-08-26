# M4 — It answers from my data

**Goal:** CSV and spreadsheet import, PostgreSQL dump import into an isolated sandbox, live read-only connections, schema notes fed by the clarification loop, and text-to-SQL with the full validation chain and the query always shown.

**Phase:** 3 (`../build-plan.md`) · **Depends on:** M3 · **Tickets:** 26 · **Estimated:** 80–115 hours

**Exit condition:** A CSV and a PostgreSQL dump both import and answer questions with the query shown; a live database connects only with read-only credentials; a hostile dump destroys only its own sandbox database; the SQL-safety eval subset scores 1.00 with no exceptions; and execution-matched text-to-SQL scores at or above 0.80.

> **Highest-risk surface in the product.** The user's real database is on the other side of it. Three constraints meet here: dumps are untrusted code (C3), generated SQL is never trusted (C2), and retrieved content is never instruction (C7).

## Included epics

| Epic | Code | Covers |
| ---- | ---- | ------ |
| CSV and spreadsheets | `CSV` | Parsing, inference, the date rule, loading |
| SQL dumps | `DUMP` | Sandbox container, import, caps, containment |
| Live connections | `CONN` | Wizard, write probe, credential encryption, health |
| Schema knowledge | `SCHEMA` | Introspection, notes, drift |
| SQL safety | `SQL` | Generation, validation, limits, dry run, roles, recording |
| Results | `RESULT` | Rendering, disclosure, states |
| Evaluation | `EVAL` | Text-to-SQL and SQL-safety suites |

---

### M4-DUMP-DEPLOY-087 — Sandbox Postgres container with a restricted role and no egress

**Type:** Story

**User Story**
- **Actor:** someone about to import a database dump a colleague sent them.
- **User Need:** the import to be unable to touch anything else they own.
- **Business Value:** a dump is a program; importing means executing arbitrary commands from a file the user probably did not read.
- *As someone importing a dump I did not write, I want it to run somewhere sealed, so that a broken or malicious file wrecks only its own copy.*

**Context / Background**
**Detailed Description:** Add the sandbox Postgres service, a separate instance from the one holding chunks, memory and the audit log, using the same image so there is one thing to bundle and learn. One database per imported source. Owned by a restricted role with no superuser rights, no ability to execute programs from a copy operation, no large-object access and no access to any other database. **The sandbox has no route to the egress proxy at all.**

**Scope**
- Sandbox service with its own volume, isolated from the main database.
- Restricted role creation with the named privileges removed.
- Network configuration giving it no outbound route, not even through the proxy.
- Per-database creation and drop operations.

**Out of Scope**
- Importing anything (M4-DUMP-ING-088).
- Caps (M4-DUMP-VAL-089).

**Acceptance Criteria**
- **Acceptance Criteria:** The sandbox comes up as its own instance. The restricted role cannot create a superuser, cannot execute a program through a copy, cannot access large objects, and cannot connect to another database in the instance. It cannot reach Askwell's own database. It cannot reach the network, including the proxy. **C3 is preserved structurally: the isolation is a role and a network boundary, not a code path that could be bypassed.**
- **Edge Cases:** The sandbox volume filling — it is capped separately from the main volume so a runaway import cannot take the product down with it. The sandbox failing to start — database sources report unavailable while document sources keep working. An orphaned sandbox database from a crashed import — reclaimed at startup rather than left occupying disk.
- **Permissions / Roles:** Single user — no roles in the product sense. Two database roles exist inside the sandbox: an owner used for import and a read-only role used for querying.
- **UI States:** `../ux/add-source.md` §3 for the surrounding copy; `../ux/library.md` §5 needs attention when the sandbox is unavailable.
- **Validation Rules:** No configuration may grant the sandbox role rights beyond its own database.
- **Audit / Logging Requirements:** Sandbox database creation and drop are decisions records.
- **Analytics Events:** Local counter of sandbox databases — nothing transmitted (C1).

**Real-World Example Scenarios**
- A dump containing a command to read a file from the host fails because the role cannot execute programs, and the failure is reported rather than silently succeeding.

**Dependencies & Assumptions**
- **Dependencies:** M0-STACK-DEPLOY-009, M0-STACK-SEC-010.
- **API / Data Touchpoints:** `sources.sandbox_db`.
- **Assumptions:** PostgreSQL-only dumps mean one sandbox engine, which keeps the image identical to the main database and saves bundle size in the offline installer.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Bring the stack up cold and confirm the sandbox service is running and separate from the main database. Connect as the restricted role and attempt each forbidden operation in turn — creating a superuser, executing a program through a copy, accessing another database, reaching the network. Each is refused. Confirm the main database is unreachable from the sandbox.
- **Other scenarios:** Kill the stack mid-import and confirm the orphaned database is reclaimed on the next start.
- **Known gaps:** Nothing imports yet. No caps yet.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:3`, deployment, security, `constraint:sandbox`
- **Granularity:** One service, one role, one network boundary. Upper bound.

---

### M4-DUMP-ING-088 — Import a PostgreSQL dump into a per-source sandbox database

**Type:** Story

**User Story**
- **Actor:** someone handed a database nobody documented.
- **User Need:** to load it and ask questions about it without writing SQL.
- **Business Value:** this is the data path that CSV cannot cover — real schemas with real relationships.
- *As someone who has just been given a database dump, I want to load it and ask about it in English, so that I do not have to reverse-engineer a schema first.*

**Context / Background**
**Detailed Description:** Import creates a fresh sandbox database for the source, loads the dump as the restricted owner role, and on success introspects the schema. Two imports cannot see each other. On any failure the sandbox database is dropped and the failure is reported with its reason. Once loaded, the sandbox database is treated exactly like a live connection — read-only, validated queries only.

**Scope**
- Per-source database creation, load, and success or failure handling.
- Progress reporting during a long load.
- Drop-on-failure with the reason retained.
- Handing off to schema introspection on success.

**Out of Scope**
- Caps (M4-DUMP-VAL-089) and the screen copy (M4-DUMP-FE-090).
- Non-PostgreSQL dumps, which are refused with routes out.

**Acceptance Criteria**
- **Acceptance Criteria:** A valid PostgreSQL dump loads into its own database and its schema is introspected. Two imported sources cannot see each other's data. A dump that fails to load leaves no partial database behind and reports the reason. The load never touches Askwell's own database.
- **Edge Cases:** A dump that partially loads then errors — the whole database is dropped, not left half-populated. A dump that creates roles or tablespaces — refused or ignored by the restricted role, and the outcome is reported. A dump with the same name as an existing source — a distinct database, since one database per source is the rule. An import interrupted by a stack restart — the partial database is reclaimed.
- **Permissions / Roles:** Single user — no roles. Not applicable in the product sense.
- **UI States:** `../ux/add-source.md` §5 indexing, dump-too-large, and the failure rows; `../states-and-edge-cases.md` §3.
- **Validation Rules:** The import path never runs against the main database, and this is enforced by connection configuration, not by convention.
- **Audit / Logging Requirements:** Import start, outcome and drop are decisions records.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A developer imports a production dump from a colleague and asks how many orders shipped late last quarter, without opening a SQL client.

**Dependencies & Assumptions**
- **Dependencies:** M4-DUMP-DEPLOY-087.
- **API / Data Touchpoints:** `sources.sandbox_db`, `sources.status`.
- **Assumptions:** v1 supports PostgreSQL dumps only; MySQL and SQL Server users connect live or export CSV, and the refusal names both routes.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, go to add a source, choose the dump route and select a PostgreSQL dump. Watch progress. When it completes, open the library and confirm the source is listed with its tables. Import a second dump and confirm neither can see the other by asking a question that would only work if they could — it must not.
- **Other scenarios:** Import a deliberately broken dump and confirm the failure is reported and no database remains.
- **Known gaps:** No caps yet, so a huge dump can still run long. No querying until the SQL path lands.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:3`, ingestion, `constraint:sandbox`
- **Granularity:** Create, load, introspect, drop-on-failure. Upper bound.

---

### M4-DUMP-VAL-089 — Size and time caps that abort the import and drop the sandbox

**Type:** Story

**User Story**
- **Actor:** someone who accidentally selected a 200 GB dump.
- **User Need:** the import to stop rather than fill their disk.
- **Business Value:** a runaway dump on a personal laptop is not an inconvenience, it is an unusable machine.
- *As someone whose laptop is also my whole life, I want a runaway import to stop itself, so that a mistake costs a minute rather than an afternoon.*

**Context / Background**
**Detailed Description:** Each import is capped at 5 GB and 10 minutes by default, both user-adjustable. Beyond either, the import aborts, the sandbox database is dropped, and the reason is reported specifically — which cap was hit and what the current setting is.

**Scope**
- Size and time measurement during import.
- Abort, drop and report on either cap.
- Adjustable caps in settings with the defaults stated.

**Out of Scope**
- Resuming a capped import — it is aborted, not paused.

**Acceptance Criteria**
- **Acceptance Criteria:** An import exceeding the size cap aborts, drops its database and names the size cap. An import exceeding the time cap does the same and names the time cap. Adjusting a cap in settings changes the behaviour of the next import. Disk usage returns to its pre-import level after an abort.
- **Edge Cases:** A dump that is small on disk but expands beyond the cap when loaded — measured on loaded size, not file size. An import that hits both caps at once — reports the one hit first. An abort during a long-running statement — the statement is terminated rather than waited on.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/add-source.md` §5 dump too large or too slow.
- **Validation Rules:** Caps are enforced during the load, not checked only at the start.
- **Audit / Logging Requirements:** The abort and its cause are decisions records; the cap change is another.
- **Analytics Events:** Local counter of aborted imports — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user selects the wrong file, sees the import abort after ten minutes with a clear message, and their disk is exactly as it was.

**Dependencies & Assumptions**
- **Dependencies:** M4-DUMP-ING-088.
- **API / Data Touchpoints:** `settings`; sandbox database size.
- **Assumptions:** Loaded size can be measured continuously without materially slowing the import.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, set the size cap low in settings, then import a dump that exceeds it. Watch the import abort and read the message naming the cap and the current setting. Check disk usage before and after — it returns to baseline. Repeat with a low time cap and confirm the same behaviour with the time reason.
- **Other scenarios:** Raise the caps and confirm the same dump now imports.
- **Known gaps:** No resume. Loaded-size measurement is approximate between checks.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:3`, validation, `constraint:sandbox`
- **Granularity:** Two caps and one abort path.

---

### M4-DUMP-FE-090 — Dump route: the calm warning and the refusal with routes out

**Type:** Story

**Human review:** copy — this ticket renders wording a user reads, specified in `docs/ux/`. The runner stops and quotes it before the pull request is merged.

**User Story**
- **Actor:** someone who does not know that a dump is executable.
- **User Need:** to be told plainly what happens, once, without theatre.
- **Business Value:** the people who understand the risk will recognise the mitigation; the people who do not are protected anyway, which is the point of the sandbox.
- *As someone importing a file a colleague sent me, I want a calm statement of what Askwell does with it, so that I understand the protection without being alarmed.*

**Context / Background**
**Detailed Description:** The dump route states plainly and once that the file contains commands, that Askwell runs it inside a sealed database that cannot reach the user's other sources, the internet or Askwell's own files, and that only that sealed copy is affected if the dump is broken or malicious. Not a modal, not a warning triangle, not a checkbox to accept. A MySQL or SQL Server dump is refused with both routes out named — connect directly, or export the tables as CSV — never a bare rejection.

**Scope**
- Dump route on the add-source screen with the statement.
- Engine detection and the refusal copy naming both alternatives.
- Progress, abort and failure rendering for the import.

**Out of Scope**
- The import mechanics (M4-DUMP-ING-088).

**Acceptance Criteria**
- **Acceptance Criteria:** The statement appears once, calmly, without a modal or an acceptance checkbox. A MySQL dump is refused with both alternatives named. A PostgreSQL dump proceeds to import with progress. Abort and failure states render with their specific reasons.
- **Edge Cases:** A file that claims to be a dump but is not — refused as an unsupported format with the supported list. A dump whose engine cannot be determined — the user is asked rather than guessed at. A compressed dump — accepted if the format is recognised, refused with the reason if not.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/add-source.md` §3 and §5.
- **Validation Rules:** The refusal must never be bare; a dead end with no route out is how someone concludes the product does not handle their data.
- **Audit / Logging Requirements:** As M4-DUMP-ING-088.
- **Analytics Events:** Local counter of refused engines — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user with a MySQL dump reads the refusal, exports the tables as CSV instead, and gets better answers because the clarification loop asks about the ambiguous columns.

**Dependencies & Assumptions**
- **Dependencies:** M4-DUMP-VAL-089, M1-ADD-FE-022.
- **API / Data Touchpoints:** Engine detection.
- **Assumptions:** Engine detection from the dump's header is reliable enough to route the message.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, go to add a source and choose the dump route. Read the statement and confirm it is calm, appears once, and requires no acknowledgement. Select a MySQL dump and read the refusal — confirm it names both alternatives. Select a PostgreSQL dump and watch it import.
- **Other scenarios:** Select a text file renamed to a dump extension and confirm it is refused as unsupported.
- **Known gaps:** Compressed formats may be limited; the refusal names which are supported.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:3`, frontend, `constraint:sandbox`
- **Granularity:** One route with three messages.

---

### M4-DUMP-SEC-091 — Containment test: a hostile dump destroys only its own database

**Type:** Story

**User Story**
- **Actor:** the maintainer who has to be able to state the isolation guarantee honestly.
- **User Need:** a test that actually attempts the attacks.
- **Business Value:** the acceptance criterion for this phase is that a hostile dump destroys only its own sandbox database, and that has to be demonstrated rather than argued.
- *As someone claiming the sandbox contains a malicious dump, I want a test that tries to escape it, so that the claim is tested rather than asserted.*

**Context / Background**
**Detailed Description:** Build a suite of hostile fixture dumps attempting privilege escalation, reading host files through a copy from a program, connecting to another database in the instance, reaching the network, exhausting disk, and running indefinitely. Each must fail, be reported, and leave nothing behind except a dropped sandbox database.

**Scope**
- Hostile fixture dumps covering the named attack shapes.
- Assertions that each fails, is reported, and leaves the main database and other sandboxes untouched.
- A verification that the main database's contents are byte-identical before and after.

**Out of Scope**
- A general security audit (M7).

**Acceptance Criteria**
- **Acceptance Criteria:** Every hostile fixture fails safely with a reported reason. Askwell's own database is unchanged after each. Other sandbox databases are unchanged. No network request escapes, confirmed against the proxy's refusal counter, which must not increase for the sandbox because it has no route at all. **C3 is preserved and the test is the evidence.**
- **Edge Cases:** A dump that succeeds in loading but contains hostile data rather than hostile commands — outside this test's scope and handled by SQL validation on the query path. A dump that crashes the sandbox instance — the instance restarts and the other sandbox databases survive.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** Failure reporting per `../ux/add-source.md` §5.
- **Validation Rules:** A hostile fixture that passes is a release blocker, not a known issue.
- **Audit / Logging Requirements:** Each attempt is logged with what was attempted and how it failed.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A dump attempting to read the host's password file fails at the role level, is reported, and the sandbox database is dropped.

**Dependencies & Assumptions**
- **Dependencies:** M4-DUMP-ING-088, M4-DUMP-VAL-089, M0-STACK-SEC-011.
- **API / Data Touchpoints:** Sandbox; main database checksum; proxy counters.
- **Assumptions:** The fixture set covers the realistic attack shapes; it is extended whenever a new one is thought of, and that is stated rather than claiming completeness.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with one good dump already imported and some documents indexed. Import each hostile fixture in turn through the normal add-source flow. After each, confirm the failure is reported in the interface, the good source still answers questions, the documents still answer questions, and the proxy's refusal counter is unchanged.
- **Other scenarios:** Run the whole hostile suite in sequence and confirm the product is fully functional afterwards.
- **Known gaps:** The fixture set is not exhaustive and the documentation says so. This is containment, not a guarantee against every possible dump.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:3`, security, test, `constraint:sandbox`
- **Granularity:** Six fixtures and their assertions. Upper bound.

---

### M4-CSV-ING-092 — Parse spreadsheets and CSVs with type and header inference

**Type:** Story

**User Story**
- **Actor:** someone with an export from a system they do not control.
- **User Need:** the file understood as a table rather than as prose.
- **Business Value:** inferring and moving on is what produces confidently wrong answers about numbers, which is the worst failure this product has.
- *As someone whose data arrives as untyped exports, I want the types and headers worked out and shown to me, so that a wrong guess is visible before it becomes a wrong answer.*

**Context / Background**
**Detailed Description:** Parse CSV and spreadsheet files, infer column types and detect whether the first row is a header, and record the inference with its confidence. Anything that cannot be inferred raises a clarification. Nothing is applied silently — type and header detection are shown for review.

**Scope**
- Parsing with delimiter and encoding detection.
- Type inference per column with confidence.
- Header detection.
- Candidate clarifications for unresolvable columns and headers.

**Out of Scope**
- The date rule (M4-CSV-ING-093) and loading (M4-CSV-ING-094).
- Multi-sheet and merged-cell semantics, which are an open question in `../data-sources.md` §8 and are handled crudely with the limitation stated.

**Acceptance Criteria**
- **Acceptance Criteria:** A CSV parses with correct delimiter and encoding. Types are inferred per column with confidence recorded. A missing header is detected and raises a question. An unresolvable column raises a question with its value distribution as evidence.
- **Edge Cases:** A file with no header at all — detected rather than treating the first data row as names. A column mixing formats such as thousands separators and plain decimals — raises a question about units and currency rather than picking one. A file with inconsistent column counts per row — reported as malformed with the row numbers rather than silently padded. An encoding that is not UTF-8 — detected, with the detection stated.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/add-source.md` §2; `../ux/clarifications.md` §3 for the resulting questions.
- **Validation Rules:** No inference is applied silently where it changes meaning.
- **Audit / Logging Requirements:** Inferences recorded as low-confidence schema notes; the source addition is a decisions record.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user imports a finance export and is asked whether an amount column mixing two number formats is all the same currency.

**Dependencies & Assumptions**
- **Dependencies:** M3-RAISE-BE-071, M1-ADD-ING-025.
- **API / Data Touchpoints:** `schema_notes`, `clarifications`.
- **Assumptions:** Multi-sheet handling is one table per sheet, stated as an assumption, with merged headers flagged rather than resolved.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a CSV with a missing header and an ambiguous amount column. Watch it parse. Open clarifications and confirm both questions are there with real value evidence. Confirm the inferred types are visible for review rather than already applied.
- **Other scenarios:** Add a semicolon-delimited file in a non-UTF-8 encoding and confirm both are detected.
- **Known gaps:** Merged cells and multi-sheet workbooks are handled crudely and the limitation is stated at import.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:3`, ingestion
- **Granularity:** Parse, infer, detect, raise. Upper bound.

---

### M4-CSV-ING-093 — Never infer silently between date formats

**Type:** Story

**User Story**
- **Actor:** someone whose export uses a date format the file cannot disambiguate.
- **User Need:** to be asked, every time.
- **Business Value:** getting it wrong produces answers that look completely reasonable and are wrong by up to eleven months, and nothing in the output reveals it.
- *As someone whose dates decide when things are due, I want to be asked which format they are, so that an invisible eleven-month error cannot happen.*

**Context / Background**
**Detailed Description:** A date column whose values do not disambiguate the format raises a clarification with discrete options, every time. It is never inferred silently. Where the data does disambiguate — a day value above twelve appears — the format is inferred and recorded, and no question is raised.

**Scope**
- Ambiguity detection specific to date formats.
- A discrete-option clarification for the ambiguous case, ranked second only to contradictions.
- Silent inference only where the data genuinely disambiguates, recorded with its evidence.

**Out of Scope**
- Timezone handling.

**Acceptance Criteria**
- **Acceptance Criteria:** A column whose dates could be either format raises a question with two clear options. A column whose values disambiguate does not raise a question and records the inferred format with the disambiguating evidence. The question ranks above abbreviation questions.
- **Edge Cases:** A column mixing formats within itself — reported as malformed rather than asked about as if it were consistent. An unambiguous ISO format — no question. A column with only a handful of rows, all ambiguous — still asked, because sample size does not make it safe.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/clarifications.md` §3 and §4 discrete options.
- **Validation Rules:** Never infer silently between the two formats when the data does not disambiguate.
- **Audit / Logging Requirements:** The answer is a decisions record; the inference where made is a low-confidence schema note with its evidence.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- An import of registration dates asks once which format applies, and every later answer about deadlines is right.

**Dependencies & Assumptions**
- **Dependencies:** M4-CSV-ING-092, M3-RAISE-BE-069.
- **API / Data Touchpoints:** `clarifications.options`, `schema_notes`.
- **Assumptions:** Two options cover the realistic cases; other formats are handled as free text where they arise.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a CSV whose date column is entirely ambiguous. Open clarifications and confirm the question offers two buttons with the values shown. Answer it, then ask a question involving those dates and confirm the answer uses the chosen interpretation. Add a second CSV whose dates disambiguate themselves and confirm no question is raised.
- **Other scenarios:** Add a file mixing formats and confirm it is reported as malformed.
- **Known gaps:** Timezones are not handled. Only two format options are offered.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** Critical
- **Labels / Component:** `phase:3`, ingestion, validation
- **Granularity:** One detection and one discrete question.

---

### M4-CSV-ING-094 — Load a CSV into the sandbox as a real table

**Type:** Story

**User Story**
- **Actor:** someone who wants to ask an aggregate question about a spreadsheet.
- **User Need:** the file queryable as a table.
- **Business Value:** counting and summing over a spreadsheet is a question retrieval cannot answer.
- *As someone with a spreadsheet of results, I want to ask how many and how much, so that I stop building pivot tables to answer one question.*

**Context / Background**
**Detailed Description:** After parsing and clarification, the CSV is loaded into the sandbox database as a real table with the confirmed types, and its schema notes are indexed. It then behaves exactly like an imported dump: read-only, validated queries only.

**Scope**
- Table creation from confirmed types and headers, in the source's sandbox database.
- Loading with row-level error reporting.
- Schema notes indexed for the new table.
- Re-loading after a clarification changes a type.

**Out of Scope**
- Query execution (the SQL epic).

**Acceptance Criteria**
- **Acceptance Criteria:** A CSV becomes a table in its own sandbox database with the confirmed types. Rows that fail to load are reported with their row numbers rather than dropped silently. Answering a type clarification re-loads the affected column. Schema notes exist for the table and its columns.
- **Edge Cases:** A very large CSV — subject to the same size and time caps as a dump. A column name that is not a valid identifier — normalised, with the original recorded as a schema note so questions using the original name still work. An empty file — refused with the reason.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/add-source.md` §5 indexing and partly indexed.
- **Validation Rules:** Load failures are always reported per row, never dropped.
- **Audit / Logging Requirements:** Load outcome is a decisions record.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A researcher loads a results spreadsheet and asks for the mean of a column grouped by condition, getting the number and the query behind it.

**Dependencies & Assumptions**
- **Dependencies:** M4-CSV-ING-093, M4-DUMP-DEPLOY-087.
- **API / Data Touchpoints:** Sandbox; `schema_notes`.
- **Assumptions:** One table per CSV, one table per sheet for a workbook, stated as an assumption.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a CSV, answer the clarifications it raises, and watch it load. Open the library and confirm the source shows its table and column count. Ask an aggregate question about it and confirm a number comes back with the query shown. Change a type clarification and confirm the column re-loads.
- **Other scenarios:** Add a CSV with several malformed rows and confirm they are reported by row number.
- **Known gaps:** Merged headers are flagged rather than resolved. Very wide files may load slowly.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:3`, ingestion, database
- **Granularity:** Create, load, index, reload.

---

### M4-CSV-FE-095 — CSV route with type and header review

**Type:** Story

**Human review:** copy — this ticket renders wording a user reads, specified in `docs/ux/`. The runner stops and quotes it before the pull request is merged.

**User Story**
- **Actor:** someone adding a spreadsheet they half remember the shape of.
- **User Need:** to see what Askwell worked out before it commits.
- **Business Value:** type and header detection are shown for review, not applied silently, because a wrong type produces a wrong number with no warning attached.
- *As someone adding an export, I want to see the detected columns and types, so that I can correct one before it matters.*

**Context / Background**
**Detailed Description:** The CSV route shows detected columns, types and header state with the inferred marker, and the clarifications raised. The source becomes askable once loaded, and partial coverage is shown while it loads.

**Scope**
- Detected schema preview with the inferred marker.
- Inline correction of a detected type before load.
- Progress and the askable marker.

**Out of Scope**
- Editing data — the viewer and the import are read-only.

**Acceptance Criteria**
- **Acceptance Criteria:** The route shows every detected column with its type and the header state, marked as inferred. A type can be corrected before loading. Clarifications raised are visible from here. Progress and the askable state render.
- **Edge Cases:** A file with fifty columns — the preview stays usable, summarising and expanding. A correction that conflicts with the data — refused at load with the offending rows named rather than accepted and silently coerced.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/add-source.md` §2 and §5; `../ux/design-system.md` §2 for the inferred colour.
- **Validation Rules:** Nothing is applied silently where it changes meaning.
- **Audit / Logging Requirements:** Pre-load corrections are decisions records.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user notices a reference-number column was typed as a number, corrects it to text before loading, and avoids losing leading zeros.

**Dependencies & Assumptions**
- **Dependencies:** M4-CSV-ING-094, M1-ADD-FE-022.
- **API / Data Touchpoints:** Detected schema; `schema_notes`.
- **Assumptions:** A pre-load correction is cheaper than a post-load re-import and is worth the extra step.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a CSV containing a column of reference numbers with leading zeros. Read the preview and see it detected as a number, marked inferred. Correct it to text. Load, then ask a question naming one of those references and confirm the leading zeros survived.
- **Other scenarios:** Correct a type incompatible with the data and confirm the load refuses with the offending rows named.
- **Known gaps:** Preview is limited for very wide files.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:3`, frontend
- **Granularity:** One preview with one correction path.

---

### M4-CONN-FE-096 — Connection wizard for a live database

**Type:** Story

**User Story**
- **Actor:** someone who already runs a database and does not want to export it.
- **User Need:** to connect Askwell to it directly.
- **Business Value:** live connections are the route that covers MySQL and SQL Server without a second sandbox engine.
- *As someone whose data lives in a database I already run, I want to point Askwell at it, so that I do not have to export anything.*

**Context / Background**
**Detailed Description:** A wizard collecting host, port, database, user and password, then connecting, probing write permissions, introspecting the schema and raising clarifications for unguessable columns. Supported engines are PostgreSQL, MySQL and MariaDB, and SQL Server.

**Scope**
- The wizard form and its validation.
- Connect, then hand off to the write probe.
- Post-connection introspection trigger.
- Connection listed in the library as a source with its read-only status.

**Out of Scope**
- The write probe itself (M4-CONN-SEC-097) and credential encryption (M4-CONN-SEC-098).

**Acceptance Criteria**
- **Acceptance Criteria:** A valid read-only connection is created, introspected and listed. Invalid input is caught before a connection attempt. The connection's read-only status is visible in settings and the library.
- **Edge Cases:** A host that does not resolve, a host that refuses, and wrong credentials must be three distinguishable messages, because they are three different fixes. A database the user can connect to but not read — reported as a permissions problem naming what is missing. A connection over a network the egress proxy blocks — the failure must name that rather than looking like a wrong host.
- **Permissions / Roles:** Single user — no roles. Not applicable in the product sense; the database role is read-only and that is a separate concern.
- **UI States:** `../ux/add-source.md` §4 and §5 connection-unreachable; `../states-and-edge-cases.md` §4.
- **Validation Rules:** Port and host validated before attempting; password never logged.
- **Audit / Logging Requirements:** Connection added or reconfigured is a decisions record, without the credential.
- **Analytics Events:** Local counter only — nothing transmitted (C1).
- **C1 note:** a live connection is an outbound connection to the user's own database. It is authorised explicitly by the user creating it, is limited to that destination, and is distinct from online AI. The proxy must be configured to permit exactly that destination and nothing else, and the settings screen must count it separately from zero.

**Dependencies & Assumptions**
- **Dependencies:** M0-STACK-SEC-010, M1-ADD-FE-022.
- **API / Data Touchpoints:** `sources.config_encrypted`, `sources.kind`.
- **Assumptions:** **Explicit assumption:** permitting a user's own database destination through the egress proxy is consistent with C1 because it is a user-authorised destination, not a model or telemetry endpoint. The settings screen must show it distinctly so the local-mode zero stays meaningful.

**Real-World Example Scenarios**
- A developer connects to a local analytics database and asks a question about it within two minutes.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, go to add a source and choose the connection route. Enter a wrong host and read the message. Enter the right host with wrong credentials and confirm a different message. Enter correct read-only credentials and watch it connect, introspect and appear in the library. Open settings and confirm it is listed with its read-only status and that the outbound-request display distinguishes it.
- **Other scenarios:** Attempt a connection to a host the proxy does not permit and confirm the message names the block.
- **Known gaps:** The write probe is not wired yet, so a write-capable credential is not refused until the next ticket.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:3`, frontend, `constraint:local-first`
- **Granularity:** One wizard with four distinguishable failures. Upper bound.

---

### M4-CONN-SEC-097 — Write-permission probe that refuses write-capable credentials

**Type:** Story

**User Story**
- **Actor:** someone who pasted their usual database credentials without thinking.
- **User Need:** to be stopped, and shown how to make a read-only user.
- **Business Value:** Askwell does not hold credentials that can damage the user's database, and telling someone to create a read-only user without showing how is where the flow dies for anyone who is not a database administrator.
- *As someone who is not a DBA, I want to be refused and handed the exact statements to create a read-only user, so that the safe path is the easy one.*

**Context / Background**
**Detailed Description:** After connecting, the wizard probes whether the credentials can write. If they can, the connection is **refused** — not warned, not overridable — naming the permission detected and the object it applies to, and offering the statements needed to create a read-only user for the detected engine.

**Scope**
- Write-permission probe for each supported engine.
- Refusal naming the detected permission and object.
- Engine-specific read-only user creation guidance offered as copyable text for the user to run themselves.

**Out of Scope**
- Creating the user on the user's behalf — Askwell never holds credentials that could.

**Acceptance Criteria**
- **Acceptance Criteria:** Credentials that can write are refused, naming the permission and the object. There is no override. Credentials that cannot write are accepted. The guidance for creating a read-only user is offered and is correct for the detected engine. **C2's independent layer is established here: the database role itself is read-only, separately from any SQL validation.**
- **Edge Cases:** Credentials whose write ability varies by schema — refused if they can write anywhere reachable. A probe that cannot complete because of insufficient introspection rights — refused with that reason, because an unverifiable credential is not an acceptable one. An engine where the probe is unreliable — refused with the reason rather than assumed safe.
- **Permissions / Roles:** Single user — no roles in the product. The database role is the subject here.
- **UI States:** `../ux/add-source.md` §4 refusal copy; `../states-and-edge-cases.md` §4 write probe.
- **Validation Rules:** Refusal is absolute; there is no warning-and-continue path.
- **Audit / Logging Requirements:** The refusal and the detected permission are decisions records.
- **Analytics Events:** Local counter of refusals — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user pastes an administrator credential, is refused with the permission named, copies the offered statements, creates a read-only user, and connects successfully.

**Dependencies & Assumptions**
- **Dependencies:** M4-CONN-FE-096.
- **API / Data Touchpoints:** The user's database; `sources`.
- **Assumptions:** The probe can be performed without writing anything, by inspecting granted privileges rather than attempting a write.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, connect to a test database with an administrator credential. Confirm the connection is refused, the specific permission is named, and there is no way to override it. Copy the offered statements, run them in your own database client to create a read-only user, then connect with that user and confirm it succeeds.
- **Other scenarios:** Use a credential that can write to one schema only and confirm it is still refused.
- **Known gaps:** Probe reliability varies by engine and the refusal says so where it applies.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:3`, security, `constraint:sql-safety`
- **Granularity:** Three engines sharing one refusal. Upper bound.

---

### M4-CONN-SEC-098 — Encrypt stored credentials at rest

**Type:** Story

**User Story**
- **Actor:** someone whose laptop was stolen.
- **User Need:** their database credentials not readable from the disk.
- **Business Value:** a copied disk must not be a credential leak.
- *As someone whose laptop could be stolen, I want my database passwords encrypted on disk, so that losing the machine is not losing the database.*

**Context / Background**
**Detailed Description:** Credentials are encrypted using a key derived from the optional passphrase plus a per-install secret, so a copied disk is not a credential leak even without a passphrase, and is materially stronger with one. The passphrase feature itself lands in M7; this ticket builds the key derivation and the per-install secret so credentials are never stored in the clear from the moment they exist.

**Scope**
- Key derivation from the per-install secret, extensible to include a passphrase.
- Encryption and decryption of stored connection configuration.
- Behaviour when the key is unavailable: connections report locked rather than failing obscurely.

**Out of Scope**
- The passphrase user interface and corpus encryption (M7).

**Acceptance Criteria**
- **Acceptance Criteria:** Stored connection configuration is unreadable without the key. Copying the database file to another machine does not yield usable credentials. Connections work normally on the original install. When a passphrase is later added, the key derivation extends to include it without re-entering credentials.
- **Edge Cases:** The per-install secret is lost — connections report that credentials cannot be decrypted and offer re-entry, rather than failing as an unreachable host. A backup restored on another machine — credentials require re-entry and the restore says so, which is the interaction with the M7 restore that must be stated.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §4 connected databases; `../ux/settings.md` §9 for the passphrase and backup interaction.
- **Validation Rules:** No credential is ever written in the clear, at any point, including in logs and error messages.
- **Audit / Logging Requirements:** Credential changes are decisions records without the value.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A user restores a backup on a new laptop and is asked to re-enter their database password, which is the correct and expected outcome.

**Dependencies & Assumptions**
- **Dependencies:** M4-CONN-FE-096, M0-FOUND-SEC-007.
- **API / Data Touchpoints:** `sources.config_encrypted`.
- **Assumptions:** The per-install secret is stored outside the database so a database copy alone is insufficient.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, create a connection with a password. Inspect the stored configuration directly and confirm the password is not readable. Copy the database volume to a second install and confirm the connection there cannot decrypt and asks for re-entry rather than reporting an unreachable host.
- **Other scenarios:** Remove the per-install secret and confirm the locked state with a re-entry path.
- **Known gaps:** No passphrase yet, so the protection is against a copied database rather than against someone with the whole machine.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:3`, security
- **Granularity:** One key path and one storage change.

---

### M4-CONN-BE-099 — Connection health and three distinguishable failures

**Type:** Story

**User Story**
- **Actor:** someone whose database went down at three in the afternoon.
- **User Need:** to be told the database is unreachable rather than that Askwell failed.
- **Business Value:** a customer's database goes down independently of Askwell, and a generic failure sends the user to the wrong place.
- *As someone whose database is not always up, I want to be told which thing failed, so that I fix the database instead of reinstalling Askwell.*

**Context / Background**
**Detailed Description:** Connections are health-checked, and at query time an unreachable database produces a specific message distinct from an empty result and from a query failure. Wrong host, refused connection and wrong credentials remain distinguishable. The library shows the last successful check, the error and a reconnect action.

**Scope**
- Periodic and on-demand health checks.
- Three distinguishable failure messages at query time.
- Library rendering of connection state with the last successful check.

**Out of Scope**
- Automatic reconnection retry policy beyond a simple backoff.

**Acceptance Criteria**
- **Acceptance Criteria:** A dead connection produces "the database is unreachable", distinct from a zero-row result and from a rejected query. The library shows the last successful check, the error and a reconnect. Recovering the database restores normal operation without recreating the connection.
- **Edge Cases:** A database that accepts connections but refuses queries — reported as a permissions problem. Intermittent connectivity — the state reflects the latest check rather than flapping in the interface on every render. A connection whose credentials were revoked — reported as a credential problem with a path to re-enter.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/library.md` §5 connection dead; `../states-and-edge-cases.md` §4 connection dead at query time.
- **Validation Rules:** Unreachable and empty must never share a message.
- **Audit / Logging Requirements:** Health transitions are logged.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user asks a question, is told the database is unreachable, checks their server, restarts it, and re-asks successfully.

**Dependencies & Assumptions**
- **Dependencies:** M4-CONN-SEC-097.
- **API / Data Touchpoints:** `sources.status`, `sources.last_error`.
- **Assumptions:** Health checks are cheap enough to run periodically without loading the user's database.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with a working connection. Ask a question and get an answer. Stop the database. Ask again and read the message — it says unreachable and does not resemble an empty result. Open the library and read the last successful check time and the error. Restart the database, use reconnect, and confirm questions work again.
- **Other scenarios:** Revoke the credential and confirm a credential-specific message.
- **Known gaps:** Health check frequency is fixed and not configurable.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:3`, backend
- **Granularity:** One check and three messages.

---

### M4-SCHEMA-ING-100 — Introspect and index the schema

**Type:** Story

**User Story**
- **Actor:** someone who has just connected a database nobody documented.
- **User Need:** Askwell to know what tables and columns exist.
- **Business Value:** the schema is what makes a natural-language question into a query at all.
- *As someone facing an undocumented schema, I want Askwell to read it, so that I can ask about it in English.*

**Context / Background**
**Detailed Description:** On connect or import, introspect tables, columns, types, keys and relationships, and index table and column names so they can be retrieved at query time. Foreign keys matter especially — they are what let the system infer a relationship rather than asking about it.

**Scope**
- Introspection across the supported engines and the sandbox.
- Indexing of table and column names for retrieval.
- Re-introspection on demand and on reconnect.

**Out of Scope**
- Schema notes from clarifications (M4-SCHEMA-ING-101).
- Drift detection (M4-SCHEMA-BE-102).

**Acceptance Criteria**
- **Acceptance Criteria:** Connecting or importing yields the table and column inventory with types and keys. Names are retrievable by relevance to a question. Re-introspection updates the inventory.
- **Edge Cases:** A schema with thousands of tables — retrieval is by relevance rather than sending everything, and the limit is stated. Views and materialised views — included and labelled. A table the read-only role cannot see — omitted, with a note that some objects were not visible.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/library.md` §2 source detail.
- **Validation Rules:** Introspection runs as the read-only role, so it can never see more than a query could.
- **Audit / Logging Requirements:** Introspection runs are logged.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A developer connects a database and immediately sees forty tables listed with their relationships, without writing anything.

**Dependencies & Assumptions**
- **Dependencies:** M4-CONN-SEC-097, M4-DUMP-ING-088.
- **API / Data Touchpoints:** `schema_notes`; the source's schema inventory.
- **Assumptions:** Relevance-based schema retrieval is necessary from the start; sending a whole large schema to a small model does not work.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, connect a database with several related tables. Open the source in the library and confirm the tables, columns and relationships are listed. Add a table in the database, use re-introspect, and confirm it appears.
- **Other scenarios:** Connect a database with a table the role cannot read and confirm the note about invisible objects.
- **Known gaps:** Stored procedures and functions are not introspected.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:3`, ingestion
- **Granularity:** Introspect and index.

---

### M4-SCHEMA-ING-101 — Schema notes from the clarification loop, retrieved with the schema

**Type:** Story

**User Story**
- **Actor:** someone whose schema is full of abbreviations.
- **User Need:** plain-language descriptions attached to the tables and columns and used when generating queries.
- **Business Value:** this moves answer accuracy more than a model upgrade, and the clarification loop is what finally populates it.
- *As someone whose columns are named things like st_cd, I want to explain them once, so that every later question about them is right.*

**Context / Background**
**Detailed Description:** Unguessable columns raise clarifications with their value distribution and row count as evidence. The answers become schema notes, embedded and retrieved alongside the schema at query time. The previous design expected an administrator to write these voluntarily, which never happens; asking at the moment of ambiguity with the data in front of the user is the version that populates.

**Scope**
- Column clarification triggers using the distribution evidence built in M3.
- Schema notes embedded and retrieved with the schema inventory at query time.
- User-supplied notes outranking inferred ones.

**Out of Scope**
- The clarification screen (M3).

**Acceptance Criteria**
- **Acceptance Criteria:** An unguessable column raises a question with its value distribution and row count. Answering writes a schema note. Query generation retrieves the note with the schema and the resulting query is correct where it previously was not. User notes are never overwritten by inferences.
- **Edge Cases:** A column with a clear name — no question, per the three tests. A column across forty thousand rows outranking one across twelve — the ranking already handles this and must be visible in which questions get asked. A note for a column that later disappears — flagged as stale rather than silently applied.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/clarifications.md` §3 with the column example; `../ux/memory.md` §2 structural facts.
- **Validation Rules:** User-supplied notes always outrank inferred ones.
- **Audit / Logging Requirements:** Answers are decisions records.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- Explaining one status code once turns a wrong count into a right one for every later question that touches it.

**Dependencies & Assumptions**
- **Dependencies:** M4-SCHEMA-ING-100, M3-APPLY-RET-078, M3-RAISE-BE-071.
- **API / Data Touchpoints:** `schema_notes`, `clarifications`.
- **Assumptions:** Value distributions can be computed cheaply from the sandbox or through a bounded query on a live connection.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, import a dump with an unlabelled code column. Ask a question that depends on knowing what the codes mean and note the poor answer. Open clarifications, read the question with its value distribution, and answer it. Ask the same question again and confirm the answer is now correct and the query visibly uses the right values.
- **Other scenarios:** Confirm a clearly named column raises no question.
- **Known gaps:** Bulk patterns across similarly named columns are asked individually.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:3`, ingestion, retrieval
- **Granularity:** One trigger and one retrieval path.

---

### M4-SCHEMA-BE-102 — Detect stale annotations when the schema drifts

**Type:** Story

**User Story**
- **Actor:** someone whose live database changed under them.
- **User Need:** to know that a description now refers to something that no longer exists.
- **Business Value:** otherwise the model is prompted with a schema that no longer matches reality, and the failure is silent.
- *As someone connected to a database other people change, I want to be told when my notes have gone stale, so that answers do not quietly degrade.*

**Context / Background**
**Detailed Description:** On re-introspection, compare the inventory with existing schema notes. A note referring to a table or column that no longer exists is flagged stale and surfaced in the library as a needs-attention reason with a fix. Stale notes are not silently deleted, because the object may return.

**Scope**
- Drift comparison on re-introspection.
- Stale flag on affected notes and the library reason.
- A fix path: edit, delete, or reattach the note to a renamed object.

**Out of Scope**
- Automatic renaming detection beyond an exact-match suggestion.

**Acceptance Criteria**
- **Acceptance Criteria:** Removing a column from the database and re-introspecting flags its note as stale and surfaces it in the library. The note is not applied to query generation while stale. The fix path allows editing, deleting or reattaching.
- **Edge Cases:** A column renamed rather than removed — a suggestion to reattach where a close match exists, never an automatic reattachment. A table temporarily invisible because of a permission change — reported as possibly invisible rather than definitely gone. Many notes going stale at once — summarised in one needs-attention reason with a count.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/library.md` §5 stale annotations; `../states-and-edge-cases.md` §4 schema drift.
- **Validation Rules:** A stale note is never used in generation.
- **Audit / Logging Requirements:** Staleness detection is logged; a reattachment or deletion is a decisions record.
- **Analytics Events:** Local counter of stale notes — nothing transmitted (C1).

**Real-World Example Scenarios**
- A colleague renames a column overnight; the next morning the library flags four stale notes and offers to reattach them.

**Dependencies & Assumptions**
- **Dependencies:** M4-SCHEMA-ING-101.
- **API / Data Touchpoints:** `schema_notes.superseded_by`; the schema inventory.
- **Assumptions:** Exact-name matching is used for reattachment suggestions; fuzzy matching risks attaching a note to the wrong column.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with a connected database and a schema note. Rename the column in the database. Use re-introspect from the library. Confirm the source shows needs attention with a stale-annotation reason, expand it, and read which note is stale. Use the fix path to reattach it to the renamed column and confirm queries use it again.
- **Other scenarios:** Drop a column entirely and confirm the note is flagged and unused.
- **Known gaps:** No automatic rename detection beyond exact matching.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** Medium
- **Labels / Component:** `phase:3`, backend
- **Granularity:** One comparison and one fix path.

---

### M4-SQL-BE-103 — Schema retrieval and SQL generation

**Type:** Story

**User Story**
- **Actor:** someone who wants a number and does not write SQL.
- **User Need:** their English question turned into a query against the right tables.
- **Business Value:** this is the whole database path; everything else in the epic exists to make it safe.
- *As someone who has a database and no appetite for SQL, I want to ask in English and get the number, so that a simple question does not cost an hour.*

**Context / Background**
**Detailed Description:** Retrieve the relevant schema subset plus schema notes plus memory for the question, then generate a query with a versioned prompt file. Retrieved schema and notes are delimited as data, never instruction. The generated query then goes through the full validation chain before it is allowed near the database.

**Scope**
- Relevance-based schema subset retrieval with notes and memory.
- Generation prompt as a versioned file with the data-not-instruction boundary.
- Selection of the correct source when several databases are connected.

**Out of Scope**
- Validation, limits, dry run and execution — their own tickets.
- Multi-step reasoning across tools (M5).

**Acceptance Criteria**
- **Acceptance Criteria:** A question against a connected database produces a candidate query using the correct tables. Schema notes are included and visibly influence the query. With several databases connected, the right one is chosen, and where the choice is ambiguous the user is asked rather than guessed at. The prompt is a versioned file.
- **Edge Cases:** A question that is not about data at all — routed to document retrieval instead, not forced into SQL. A question spanning two databases — not supported in v1, and the response says so rather than producing a wrong query. A schema too large for the context — relevance retrieval bounds it and the trace records what was sent.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §3 generated SQL; `../states-and-edge-cases.md` §4 no connections configured — a database question with no connection says so rather than abstaining generically.
- **Validation Rules:** Generation never runs against the database; it produces text that must then be validated.
- **Audit / Logging Requirements:** The generated query is recorded whether or not it is executed.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- "How many orders shipped late last quarter?" becomes a query joining orders and shipments using the user's own note about the status codes.

**Dependencies & Assumptions**
- **Dependencies:** M4-SCHEMA-ING-101, M1-ASK-BE-037.
- **API / Data Touchpoints:** Schema inventory; `schema_notes`; `memory`; prompt files.
- **Assumptions:** Cross-database questions are out of scope for v1 and are refused explicitly rather than attempted.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with an imported dump and answered schema clarifications. Ask a counting question in English. Observe the step labels naming schema lookup and the query. Read the shown query and confirm it uses the right tables and the meanings you supplied. Ask a document question and confirm it does not attempt SQL.
- **Other scenarios:** Connect two databases and ask an ambiguous question — confirm you are asked which one.
- **Known gaps:** No cross-database queries. No multi-step reasoning until M5.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:3`, backend, `constraint:sql-safety`, `constraint:injection`
- **Granularity:** Retrieval plus generation. Upper bound.

---

### M4-SQL-VAL-104 — Parse generated SQL and reject anything that is not a single read

**Type:** Story

**User Story**
- **Actor:** someone whose production database Askwell is connected to.
- **User Need:** absolute certainty that a generated statement cannot modify anything.
- **Business Value:** the user's real database is on the other side of this check.
- *As someone who connected a real database, I want generated SQL parsed and rejected unless it is a single read, so that a model mistake cannot become a data loss.*

**Context / Background**
**Detailed Description:** Every generated statement is parsed with `sqlglot` and rejected unless it is a single `SELECT` or `WITH`. **Regex filtering is not sufficient and is not acceptable, even temporarily, even in a branch** — it misses nested statements, comment tricks and dialect quirks. This is one of two independent layers; the read-only database role is the other, and neither is allowed to be the only one.

**Scope**
- Parsing with the correct dialect per engine.
- Rejection of anything that is not a single read statement, including multiple statements, data-modifying statements, definition statements, and anything hidden in a comment or a nested expression.
- A recorded rejection reason for every refusal.

**Out of Scope**
- Limit injection (M4-SQL-VAL-105), dry run (M4-SQL-VAL-106) and role enforcement (M4-SQL-DB-107) — the other layers.

**Acceptance Criteria**
- **Acceptance Criteria:** A single read statement passes. Multiple statements, any data-modifying statement, any definition statement, and a read with a trailing modification are all rejected with a reason. A statement using comments or nesting to disguise a modification is rejected. **No regex-based filtering exists anywhere in the path, and a test asserts the parser is the gate.**
- **Edge Cases:** A dialect-specific construct the parser does not recognise — rejected, because an unparseable statement is not a safe one. A read that calls a function with side effects — rejected where the parser can detect it, and the residual risk is documented honestly rather than overclaimed. A very long generated statement — parsed within a bounded time or rejected on timeout.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../states-and-edge-cases.md` §4 generated SQL rejected — the user sees "I could not answer that safely" and **the SQL is shown**, because disclosure is unconditional.
- **Validation Rules:** Single `SELECT` or `WITH` only. Rejection is the default for anything uncertain.
- **Audit / Logging Requirements:** **Rejected SQL is recorded with its reason** — it is the signal that a prompt change has degraded generation, and it is invisible unless logged.
- **Analytics Events:** Local counter of rejections — nothing transmitted (C1).

**Real-World Example Scenarios**
- A model produces a read followed by a delete; the parser rejects the whole statement, the user sees the refusal and the SQL, and nothing reaches the database.

**Dependencies & Assumptions**
- **Dependencies:** M4-SQL-BE-103.
- **API / Data Touchpoints:** Validation module; `messages.trace` rejection reason.
- **Assumptions:** The parser supports every engine dialect in scope; where it does not, the statement is rejected rather than passed through.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with a connected database. Through the eval fixtures or a test harness, submit each hostile statement shape in turn — two statements, a delete, a definition statement, a commented modification, a nested modification. Confirm each is refused, that the refusal message is the safe-answer message, and that the SQL is shown to the user in every case. Then ask a normal question and confirm it succeeds.
- **Other scenarios:** Search the codebase for regex-based SQL filtering; there must be none.
- **Known gaps:** Function side effects are only partly detectable and this is documented rather than claimed as covered.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:3`, validation, `constraint:sql-safety`
- **Granularity:** One parser gate with its rejection taxonomy. Upper bound.

---

### M4-SQL-VAL-105 — Inject a row limit and make it visible in the shown SQL

**Type:** Story

**User Story**
- **Actor:** an analyst reading a result table.
- **User Need:** to know whether they are seeing everything.
- **Business Value:** a silently truncated result an analyst believes is complete is a wrong answer with no warning attached.
- *As someone about to quote a number, I want to know if the result was truncated, so that I do not report a partial figure as a total.*

**Context / Background**
**Detailed Description:** Where a validated query has no aggregate and no explicit limit, a limit of 1000 is injected. **The injected limit is visible in the SQL shown to the user**, and the result is labelled as showing the first N of possibly more. The limit is adjustable in settings.

**Scope**
- Limit injection where appropriate, skipped for aggregates and explicit limits.
- The injected limit visible in the disclosed SQL, distinguishable from one the model wrote.
- Result labelling when the limit was reached.

**Out of Scope**
- Pagination of a large result (M4-RESULT-FE-109).

**Acceptance Criteria**
- **Acceptance Criteria:** A query with no aggregate and no limit receives one, and the disclosed SQL shows it marked as added by Askwell. A query with an aggregate does not. A result that reached the limit is labelled as showing the first N of possibly more. The default is adjustable.
- **Edge Cases:** A query with an aggregate in a subquery but not at the top level — limited, because the top-level result is a row set. A query already limited to more than the default — left alone, and the disclosure shows the model's own limit. A result exactly at the limit — labelled, because it is indistinguishable from truncation.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../states-and-edge-cases.md` §4 limit auto-injected; `../ux/ask.md` §4 expand SQL with the limit visible.
- **Validation Rules:** Injection happens after parsing and before execution, never by string manipulation of the original text.
- **Audit / Logging Requirements:** The injected limit is recorded in the trace and the interaction record.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user asks for all overdue invoices, sees exactly 1000 rows with a label saying there may be more, and narrows the question.

**Dependencies & Assumptions**
- **Dependencies:** M4-SQL-VAL-104.
- **API / Data Touchpoints:** Validation module; `settings`.
- **Assumptions:** 1000 is a sensible default for a laptop and is adjustable.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with a database containing more than a thousand rows in a table. Ask a question that would return all of them. Read the result — it is labelled as the first thousand of possibly more. Expand the SQL and see the limit marked as added by Askwell. Ask a counting question and confirm no limit was added.
- **Other scenarios:** Lower the limit in settings and confirm the next query uses it.
- **Known gaps:** No pagination beyond the limit until the result ticket.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** Critical
- **Labels / Component:** `phase:3`, validation, `constraint:sql-safety`
- **Granularity:** One injection rule and one label.

---

### M4-SQL-VAL-106 — Dry run before execution

**Type:** Task

**User Story**
- **Actor:** someone whose database is slow and busy.
- **User Need:** a broken query caught before it runs.
- **Business Value:** a query that cannot be planned should never be executed against a real database.
- *As someone whose database serves other things, I want an invalid query caught before it runs, so that Askwell is not a source of load.*

**Context / Background**
**Detailed Description:** After validation and limit injection, the query is planned without execution. A planning failure means the query is not executed and the user sees the same safe-answer message with the query shown. Planning failure is recorded distinctly from validation rejection, because they indicate different problems.

**Scope**
- Plan-only execution against the target source.
- Distinct recording of a planning failure.
- The user-facing message reusing the safe-answer copy with the query shown.

**Out of Scope**
- Cost-based refusal of an expensive query — not in v1, and the statement timeout covers the runaway case.

**Acceptance Criteria**
- **Acceptance Criteria:** A query referring to a non-existent column fails planning and is not executed. A valid query plans and proceeds. A planning failure is recorded distinctly from a validation rejection. The user sees the safe-answer message with the query.
- **Edge Cases:** A database that does not support plan-only execution — the step is skipped with that recorded, rather than silently treated as passed. Planning that itself times out — treated as a failure. A plan that succeeds but execution then fails — a separate error path with its own message.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../states-and-edge-cases.md` §4 dry-run fails.
- **Validation Rules:** Planning runs as the read-only role, like execution.
- **Audit / Logging Requirements:** Planning failures are recorded with the query and the reason.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A generated query references a column that was dropped last week; planning fails, nothing runs, and the stale-annotation flag explains why.

**Dependencies & Assumptions**
- **Dependencies:** M4-SQL-VAL-105.
- **API / Data Touchpoints:** Target database; trace.
- **Assumptions:** Plan-only execution is available on all three supported engines; where it is not, the omission is recorded.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with a connected database. Ask a question, then drop a column the generated query uses and ask again. Confirm the failure happens before execution, the message is the safe-answer message, and the query is shown. Check the trace and confirm it is recorded as a planning failure rather than a validation rejection.
- **Other scenarios:** Confirm a valid query still runs normally.
- **Known gaps:** No cost-based refusal.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:3`, validation, `constraint:sql-safety`
- **Granularity:** One step and one recording distinction.

---

### M4-SQL-DB-107 — Independent read-only role and statement timeout

**Type:** Story

**User Story**
- **Actor:** someone relying on more than one safety layer.
- **User Need:** the database itself to refuse a write, independently of any parsing.
- **Business Value:** the validation and the role are two independent layers, and a design where either is the only one is a design with a single point of failure.
- *As someone whose database matters, I want the database itself to refuse writes, so that a parser bug is not the only thing standing between the model and my data.*

**Context / Background**
**Detailed Description:** Every query executes as a read-only role, enforced at the database, with a 30-second statement timeout per session. For the sandbox this is a separate role from the import owner. For live connections it is the user's own read-only credential, already enforced by the write probe. The timeout produces a specific message with the query and a suggestion to narrow it.

**Scope**
- Read-only execution role for the sandbox, distinct from the import owner.
- Statement timeout applied per session on every engine.
- The timeout message with the query and the narrowing suggestion.

**Out of Scope**
- Query cost estimation.

**Acceptance Criteria**
- **Acceptance Criteria:** Execution uses a role that cannot write, verified by attempting a write directly as that role and being refused. A query exceeding 30 seconds is terminated and reported as taking too long, with the query and a suggestion. The sandbox's execution role cannot modify the imported data.
- **Edge Cases:** A long-running aggregate that legitimately needs more time — the timeout is adjustable in settings and the message says so. A timeout during planning — reported as a planning failure. A role misconfiguration — startup refuses rather than falling back to a writable role.
- **Permissions / Roles:** Single user — no roles in the product. Two database roles per sandbox: import owner and query reader.
- **UI States:** `../states-and-edge-cases.md` §4 statement timeout.
- **Validation Rules:** The application must never execute a generated query as a role that can write, and this is checked at startup.
- **Audit / Logging Requirements:** Timeouts are recorded with the query and duration.
- **Analytics Events:** Local counter of timeouts — nothing transmitted (C1).

**Real-World Example Scenarios**
- A question producing an accidental cross join is terminated after thirty seconds with a suggestion to narrow it, rather than pinning the user's machine.

**Dependencies & Assumptions**
- **Dependencies:** M4-DUMP-DEPLOY-087, M4-CONN-SEC-097, M0-DATA-DB-014.
- **API / Data Touchpoints:** Database roles; `settings`.
- **Assumptions:** Thirty seconds is right for a laptop and is adjustable for someone with a large database.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with an imported dump. Connect directly as the query role and attempt an insert — it is refused by the database. Then ask a question designed to run long and confirm it is terminated at thirty seconds with a message naming the timeout, showing the query and suggesting a narrower question.
- **Other scenarios:** Misconfigure the role to be writable and confirm the application refuses to start.
- **Known gaps:** No cost estimation, so a query can still run to the full timeout.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:3`, database, security, `constraint:sql-safety`
- **Granularity:** One role and one timeout.

---

### M4-SQL-OBS-108 — Record executed and rejected SQL with reasons

**Type:** Task

**User Story**
- **Actor:** the maintainer whose prompt change quietly degraded generation.
- **User Need:** rejected SQL recorded, not just successful queries.
- **Business Value:** rejected SQL is the signal that a prompt change has degraded generation, and it is invisible unless recorded.
- *As someone changing the SQL prompt, I want the rejections recorded, so that a degradation shows up in the log rather than in a user's confusion.*

**Context / Background**
**Detailed Description:** Every generated query is recorded in the interaction log whether executed or rejected, with the validation outcome, the rejection reason where applicable, the injected limit, the row count and the duration. This is deliberate and is called out in the audit design.

**Scope**
- Interaction record fields for generated SQL, validation outcome, rejection reason, injected limit, rows and duration.
- The same fields in the trace for the trace screen in M5.
- A local view of the rejection rate over a window.

**Out of Scope**
- Any transmission of any of this.

**Acceptance Criteria**
- **Acceptance Criteria:** Every generated query appears in the interaction log with its outcome. A rejected query appears with its reason. The rejection rate is computable locally over a window. The log chain still verifies.
- **Edge Cases:** A query rejected before generation completed — recorded as far as it got. A very long query — stored in full in the interaction record, because truncating the thing you are trying to diagnose defeats the purpose. A query containing data that looks like a credential — the query text is stored as generated; no user credential appears in generated SQL, and this is asserted by a test.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/trace.md` §3 generated SQL and whether validation accepted it.
- **Validation Rules:** Rejections are never discarded.
- **Audit / Logging Requirements:** This ticket is the audit requirement for the SQL path.
- **Analytics Events:** Local counter and rate only — nothing transmitted (C1).

**Real-World Example Scenarios**
- After a prompt change the rejection rate goes from two percent to eighteen, which is visible in the log before any user complains.

**Dependencies & Assumptions**
- **Dependencies:** M4-SQL-VAL-104, M1-ASK-OBS-041.
- **API / Data Touchpoints:** `audit_interactions`; `messages.trace`.
- **Assumptions:** Storing full query text is affordable within the interaction store's budget.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with a connected database. Ask several data questions, including one crafted to produce a rejection. Compute the local rejection rate and confirm it reflects them. Run log verification and confirm the chain is intact.
- **Other scenarios:** Confirm a rejected query's text and reason are both present.
- **Known gaps:** No trace screen until M5, so this is inspectable only through the log.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:3`, observability, `constraint:audit`, `constraint:sql-safety`
- **Granularity:** One record extension.

---

### M4-RESULT-FE-109 — Render results with counts, pagination and the truncation label

**Type:** Story

**User Story**
- **Actor:** someone who asked for a list rather than a number.
- **User Need:** a readable table with an honest row count.
- **Business Value:** an answer built on a truncated table that looks complete is the worst kind of wrong.
- *As someone reading a result table, I want the row count and a clear truncation label, so that I know what I am looking at.*

**Context / Background**
**Detailed Description:** Render query results as a table with the row count, paginated for large results, and labelled as the first N of possibly more where the limit was reached. Results appear in the conversation with the same provenance treatment as documents — the query is the citation.

**Scope**
- Table rendering with column headers and types respected.
- Pagination with the total or the known-at-least count.
- Truncation labelling tied to the injected limit.
- Result rendering in the source viewer for a database source.

**Out of Scope**
- Charts — this is not a dashboard tool.
- Export of a result set (M7 covers export of everything).

**Acceptance Criteria**
- **Acceptance Criteria:** A result renders as a table with its row count. A large result paginates. A truncated result is labelled. A zero-row result is distinct from an error and from abstention. Clicking through opens the database source view with the query and its rows.
- **Edge Cases:** A very wide result — horizontal scrolling rather than a broken layout. A result with null values — rendered distinguishably from empty strings. A single-value result — rendered as a number in the answer rather than a one-cell table.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../states-and-edge-cases.md` §4 zero rows and very large result; `../ux/source-viewer.md` §2 database rendering.
- **Validation Rules:** A truncated result must always be labelled.
- **Audit / Logging Requirements:** Row counts are on the interaction record.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user asks for late shipments, gets a table of forty rows with the count shown, and clicks through to see the query that produced it.

**Dependencies & Assumptions**
- **Dependencies:** M4-SQL-DB-107, M1-VIEW-FE-047.
- **API / Data Touchpoints:** Result sets; `messages`.
- **Assumptions:** Results are rendered from a stored snapshot rather than re-queried on pagination, so the page the user reads is internally consistent.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with an imported dump. Ask for a list that returns several hundred rows. Confirm the table renders with the row count and pagination. Ask something that returns nothing and confirm the message says no matching records with the query shown, and does not look like an error or an abstention. Ask for a single number and confirm it renders as a number.
- **Other scenarios:** Ask for a result that hits the limit and confirm the truncation label.
- **Known gaps:** No charts, no result export.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:3`, frontend
- **Granularity:** One table with four states.

---

### M4-RESULT-FE-110 — SQL disclosure, collapsed by default, always available

**Type:** Story

**User Story**
- **Actor:** an analyst who has to defend a number.
- **User Need:** the query that produced it, always, without asking.
- **Business Value:** a number you cannot trace is not worth much, and disclosure is unconditional — including for rejected queries.
- *As someone who will be asked where this number came from, I want the query attached to the answer, so that I can check it rather than trust it.*

**Context / Background**
**Detailed Description:** The generated query is always shown, collapsed by default, with the injected limit visible where one was added. This applies to rejected queries too — a refusal shows the SQL, because that is the signal that something is wrong with generation and hiding it helps nobody.

**Scope**
- Collapsed disclosure attached to every database answer.
- Expanded view with syntax legibility and the injected limit marked.
- Disclosure on refusals and timeouts as well as successes.
- Copy-query action.

**Out of Scope**
- Editing and re-running a query — tracked as a future improvement; the settled metric watches how often generated SQL is edited, which implies the capability, and it is deliberately deferred past v1.

**Acceptance Criteria**
- **Acceptance Criteria:** Every database answer carries its query, collapsed. Expanding shows it with the injected limit marked. A refused query is shown with its refusal. A timed-out query is shown with its timeout. The query can be copied.
- **Edge Cases:** A very long query — expands with scrolling rather than truncation. Several queries in one turn once multi-step arrives in M5 — each disclosed separately, in order. A query against a source that has since been deleted — still shown, since it is part of the answer's record.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §4 expand SQL; `../states-and-edge-cases.md` §4 rejected SQL is shown.
- **Validation Rules:** Disclosure is unconditional and may never be made optional.
- **Audit / Logging Requirements:** As M4-SQL-OBS-108.
- **Analytics Events:** Local counter of disclosures expanded — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user expands the query, sees a join they did not expect, and realises the question was ambiguous rather than the answer wrong.

**Dependencies & Assumptions**
- **Dependencies:** M4-RESULT-FE-109, M4-SQL-VAL-105.
- **API / Data Touchpoints:** `messages.trace` sql step.
- **Assumptions:** Collapsed-by-default is the right balance; the query is present but not in the way.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask a data question, and confirm the answer shows a collapsed query control. Expand it and read the query with the added limit marked. Copy it and paste it into your own database client to confirm it is the query that ran. Then trigger a rejection and confirm the SQL is still shown.
- **Other scenarios:** Trigger a timeout and confirm the query is shown with it.
- **Known gaps:** No editing or re-running of a query in v1.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** Critical
- **Labels / Component:** `phase:3`, frontend, `constraint:sql-safety`
- **Granularity:** One disclosure across four outcomes.

---

### M4-RESULT-FE-111 — Database states: no connections, unreachable, zero rows, timeout, rejected

**Type:** Story

**Human review:** copy — this ticket renders wording a user reads, specified in `docs/ux/`. The runner stops and quotes it before the pull request is merged.

**User Story**
- **Actor:** someone whose data question did not produce data.
- **User Need:** to know which of five different things happened.
- **Business Value:** abstaining as if the corpus lacks it is misleading when the data exists and is simply not connected; five failures with one message is five wrong diagnoses.
- *As someone whose question returned nothing, I want to know whether there is no connection, no rows, or a broken query, so that I fix the right thing.*

**Context / Background**
**Detailed Description:** Build the five distinct database states on Ask and in the library: no connections configured, connection unreachable, zero rows, statement timeout, and validation rejection. Each has its own message and its own next action. A database question with no connection configured says so rather than abstaining generically.

**Scope**
- Five states with their copy and their next actions.
- Routing a database-shaped question with no connection to the right message.
- The empty state for database connections naming what connecting enables and that credentials must be read-only.

**Out of Scope**
- The underlying detection, which is in the other tickets.

**Acceptance Criteria**
- **Acceptance Criteria:** Each of the five states renders distinctly with its own message and action. A database question with no connections configured says so and offers to connect. Zero rows shows the query so the analyst can see whether the question or the query was wrong.
- **Edge Cases:** A question that could be answered from documents but was routed to data — falls back to documents rather than reporting no connection. A source that exists but is still importing — says importing rather than unreachable. Several connections where one is down — the message names which.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../states-and-edge-cases.md` §4 in full; `../states-and-edge-cases.md` §7 database connections empty state.
- **Validation Rules:** No two of the five may share a message.
- **Audit / Logging Requirements:** Each outcome is recorded distinctly.
- **Analytics Events:** Local counters per outcome — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user asks about sales before connecting anything and is told to connect a database rather than being told their files do not cover it.

**Dependencies & Assumptions**
- **Dependencies:** M4-RESULT-FE-110, M4-CONN-BE-099, M4-SQL-VAL-106.
- **API / Data Touchpoints:** Source states; query outcomes.
- **Assumptions:** A database-shaped question can be recognised well enough to route to the no-connections message rather than to abstention.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** On a fresh install with documents only, ask a question that is clearly about tabular data and confirm the message says no database is connected and offers to connect one. Connect a database, then produce each of the other four states in turn — stop the database, ask for something with no matching rows, ask something that runs long, and trigger a rejection — confirming each message is distinct and each offers a sensible next step.
- **Other scenarios:** Ask a question answerable from documents while a database is connected and confirm it is answered from documents.
- **Known gaps:** Question routing between documents and data is heuristic and will occasionally choose wrongly; the trace shows which path was taken.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:3`, frontend, validation
- **Granularity:** Five states with shared plumbing.

---

### M4-EVAL-TEST-112 — Text-to-SQL and SQL-safety eval suites

**Type:** Task

**User Story**
- **Actor:** the maintainer accepting the database phase.
- **User Need:** execution-matched text-to-SQL scoring and a safety suite that must score perfectly.
- **Business Value:** the phase's acceptance is that SQL safety scores 1.00 with no exceptions and execution match reaches 0.80.
- *As someone signing off the riskiest part of the product, I want a safety suite with no tolerance for failure, so that the sign-off means something.*

**Context / Background**
**Detailed Description:** Forty execution-matched text-to-SQL tasks over a fixture database, scored by comparing result sets rather than query text, with a 0.80 mean bar. Ten SQL-safety tasks covering write attempts and injection, with a bar of 1.00 — no exceptions. Both run three times with worst-case reported.

**Scope**
- Fixture database with a realistic schema, including unguessable columns that need schema notes.
- Forty execution-matched tasks and ten safety tasks.
- Integration into the gate with the 1.00 bar enforced as a hard failure.

**Out of Scope**
- Tool-selection tasks (M5).

**Acceptance Criteria**
- **Acceptance Criteria:** Text-to-SQL is scored by result-set equivalence, not string comparison. The safety suite scores 1.00 or the gate fails. Both report worst-case beside mean. A deliberately weakened validator fails the safety suite.
- **Edge Cases:** A task with several correct queries producing the same result — accepted, which is why matching is on results. A task whose result depends on schema notes — included deliberately, since that is what the clarification loop is for. A safety task that the validator rejects for the wrong reason — scored as a pass on safety but flagged, because the outcome is right and the reasoning is worth knowing.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None.
- **Validation Rules:** The 1.00 bar may not be lowered, for any reason, in any branch.
- **Audit / Logging Requirements:** Results recorded with model and prompt version.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A prompt improvement raises execution match but introduces one safety failure; the change is rejected on the safety bar alone.

**Dependencies & Assumptions**
- **Dependencies:** M4-SQL-VAL-104, M4-SQL-DB-107, M2-EVAL-TEST-063.
- **API / Data Touchpoints:** Fixture database; the SQL path.
- **Assumptions:** The fixture schema is representative enough that a score on it predicts behaviour on a real one; this is stated rather than assumed silently.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, import the fixture database through the normal dump route, answer its schema clarifications, then run both suites. Read the execution-match score and the safety score. Weaken the validator deliberately and re-run — the safety suite must fail, which proves it measures what it claims.
- **Other scenarios:** Remove the schema notes and confirm the execution-match score drops, which demonstrates the clarification loop's contribution.
- **Known gaps:** One fixture schema only. English only.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:3`, test, `eval`, `constraint:sql-safety`
- **Granularity:** Two suites over one fixture. Upper bound.
