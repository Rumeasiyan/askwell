# Data sources

How material gets into VaultQ. Four kinds, two of which are new since the repositioning.

| Kind | What it is | Risk |
| ---- | ---------- | ---- |
| **Files** | PDF, DOCX, XLSX, PPTX, TXT, MD, HTML, images | Low — parsed, never executed |
| **CSV / spreadsheet** | Tabular export with no schema | Low, but ambiguous — the clarification loop's best case |
| **SQL dump** | `.sql`, `.dump`, `.backup` | **High — this is executable code** |
| **Live connection** | PostgreSQL, MySQL/MariaDB, SQL Server | Medium — real credentials against a real database |

---

## 1. Files

Upload → type detection → extraction → OCR fallback for scanned pages → structure-aware chunking → embedding → index.

- Chunking respects headings, table boundaries and list items. A chunk splitting a table row from its header is a defect.
- Every chunk keeps source document, page, section heading, ingestion timestamp.
- Re-adding a changed document **supersedes** the old version rather than duplicating it, so answers can say "as of the June revision".
- Duplicate detection by `sha256` — the same file added twice is recognised, not re-ingested.
- Scanned pages that OCR poorly are flagged low-confidence and raise a clarification (`memory-and-clarification.md` §1). They are still indexed; the user is told they will retrieve badly.

Deletion tombstones the document (issue #11): content and embedding cleared, row retained, old citations resolve to "deleted on `<date>`".

---

## 2. CSV and spreadsheets

A CSV has no types, no constraints and frequently no usable header. Inferring and moving on is what produces confidently wrong answers about numbers, which is the worst failure this product has.

Pipeline: parse → infer types and header → **raise clarifications for what cannot be inferred** → load into the sandbox database (§3) as a real table → index schema notes.

**This is where the clarification loop pays for itself immediately.** The questions are concrete and the user can always answer them:

- "`dt_reg` looks like a date in DD/MM/YYYY — correct, or MM/DD?"
- "Column 3 has no header. What is it?"
- "`amount` mixes `1,200.00` and `1200.5`. Same currency, same units?"

Date format ambiguity is the one to be most careful about. `03/04/2025` is valid in two formats meaning different months, and getting it wrong produces answers that look completely reasonable and are wrong by up to eleven months. **Never infer silently between DD/MM and MM/DD when the data does not disambiguate** — ask, every time.

---

## 3. SQL dumps — the sandbox

**A `.sql` dump is a program.** Importing one means executing arbitrary DDL and DML from a file the user supplied and probably did not read. `sqlglot` validation (C2) governs *querying* and cannot govern *loading* — a dump that cannot write cannot import.

So imports never touch VaultQ's own database.

### Isolation

- A **separate Postgres instance** — the `sandbox` container — distinct from the one holding VaultQ's chunks, memory and audit log.
- **One database per imported source**, so two imports cannot see each other.
- Owned by a **restricted role**: no superuser, no `COPY ... FROM PROGRAM`, no large-object access, no access to any other database.
- No network egress from the sandbox container.
- A per-import size and time cap, so a runaway dump fails rather than filling the disk.

A malicious or broken dump wrecks its own sandbox database. VaultQ drops it and reports the failure.

### Why this is in from the start

Retrofitting isolation after imports exist means migrating data on users' machines — the worst possible place to run a migration, because there is no operator and no rollback. The sandbox container is one extra service, which is a real cost (`architecture.md` §2 treats container count as a cost), and it is worth it here.

### After loading

Once loaded, the sandbox database is treated exactly like a live connection: read-only queries only, `sqlglot`-validated, schema notes indexed, clarifications raised for unguessable columns. The import path is dangerous; the query path is the same as everything else.

---

## 4. Live connections

Connect to a database the user already runs.

- **Read-only credentials only.** The wizard runs a write-permission probe and **refuses** credentials that pass it. Not a warning — a refusal.
- Credentials encrypted at rest with a key derived from the optional passphrase plus a per-install secret.
- Schema introspected on connect; unguessable columns raise clarifications.
- Query path: schema retrieval → SQL generation → `sqlglot` validation → `EXPLAIN` dry run → execution under limits → formatting.

Safety layers, all mandatory:

1. Database role is read-only, enforced at the database.
2. Generated SQL parsed with `sqlglot`; anything not a single `SELECT`/`WITH` is rejected before it reaches the driver. **Regex filtering is not acceptable.**
3. Automatic `LIMIT` injection (default 1000) where there is no aggregate and no explicit limit — and the injected limit is **visible in the SQL shown to the user**, so a truncated result is never mistaken for a complete one.
4. `statement_timeout` of 30s per session.
5. Every executed query recorded in the interaction log, including rejected ones (`audit-log.md` §7).

**The generated SQL is always shown**, collapsed by default. A number you cannot trace is not worth much.

The column-level access control from the previous design is **removed** — it existed to hide columns from other roles, and there are no other roles.

---

## 5. Schema notes

Every database-backed source — imported or live — carries plain-language descriptions of its tables and columns, embedded and retrieved alongside the schema at query time.

This moves answer accuracy more than a model upgrade. `st_cd` is unguessable; `st_cd — student status code: A=active, T=transferred, D=dropped` is trivial.

The previous design expected an administrator to write these voluntarily, which never happens. They now come from the clarification loop, generated at the moment of ambiguity with the source in front of the user. User-supplied notes always outrank inferred ones and are never silently overwritten.

---

## 6. Failure handling

| Failure | Behaviour |
| ------- | --------- |
| Extraction fails (corrupt, encrypted, password-protected) | Listed as failed with the reason. Retry available. **Never silently dropped.** |
| OCR yields little text | Ingested, flagged low-confidence, clarification raised |
| Unsupported format | Rejected at add time with the supported list |
| Dump exceeds size or time cap | Import aborted, sandbox database dropped, reason reported |
| Dump fails to load | Same. The partial sandbox is destroyed, not left behind |
| Live connection dies mid-query | "The database is unreachable" — distinct from an empty result |
| Write-capable credentials offered | Refused, naming the permission detected |
| Embedding job fails after retries | Visible with the error and a retry. Never silently dropped |
| Disk budget hit during ingestion | Ingestion refused first, questions keep working (`audit-log.md` §3) |

---

## 7. Settled scope

**v1 imports PostgreSQL dumps only.** MySQL and SQL Server dumps are not supported as dumps.

A MySQL dump cannot load into a Postgres sandbox, so supporting it means either a second sandbox engine — a ninth container on someone's laptop — or a translation layer, which is a large and permanently leaky piece of work. Neither is worth it in v1 when two adequate paths already exist: **live connections already support MySQL and SQL Server** and need no dump at all, and **CSV export exists in every database tool ever made** and lands in the same sandbox with better clarification behaviour.

The unsupported-format message must say this explicitly — "MySQL dumps are not supported; connect directly, or export the tables as CSV" — rather than a bare rejection. A dead end with no route out of it is how someone concludes the product does not handle their data.

**Sandbox caps: 5 GB and 10 minutes per import.** Beyond either, the import aborts and the sandbox database is dropped. Both user-adjustable.

## 8. Open

1. **Excel with multiple sheets and merged cells.** Whether each sheet becomes a table, and how merged headers are handled. Common in real files and unresolved.
