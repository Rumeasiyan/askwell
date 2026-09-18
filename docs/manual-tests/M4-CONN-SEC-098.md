# Manual test — M4-CONN-SEC-098, encrypting stored connection credentials at rest

**Ticket:** `M4-CONN-SEC-098` — a live connection's stored configuration
(`sources.config_encrypted`) is encrypted with a key derived from a per-install secret, so a
copied database volume alone is not a credential leak, and a lost install secret reports as
"locked, re-enter" rather than a misleading connection failure.
**Version under test:** `0.4.10`
**Time:** about 25 minutes, plus a first stack build.
**Who can run it:** a browser and a terminal, with `podman compose exec` access to the
`sandbox` container to stand up a database to connect to, and host filesystem access to the
`ASKWELL_RUN_DIR` bind mount to inspect and delete the install secret.

**What is being checked.** `api/src/askwell/crypto.py` (`load_or_create_install_secret`,
`derive_key`, `encrypt`, `decrypt`, `CredentialsLocked`); `api/src/askwell/connections.py`'s
`create_connection_source` and `run_introspection`; `Settings.install_secret_path`
(`ASKWELL_INSTALL_SECRET_PATH`); the `credentials_locked` reason code and its `attention`
surfacing in the library and settings screens built by `M4-CONN-FE-096`.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **No passphrase.** M7's scope. `derive_key` already accepts one and folds it into the same
  HKDF call, but nothing in this build ever passes one — the key today is derived from the
  install secret alone.
- **No write-permission probe interaction beyond what `M4-CONN-SEC-097` already built.** This
  ticket only changes what happens to the bytes once a connection is accepted; the write
  refusal path is unaffected and not re-tested here.
- **No re-encryption or key rotation.** If the install secret is regenerated, every
  already-stored connection becomes permanently locked — there is no path in this build that
  re-encrypts existing rows under a new key. Re-entry means deleting and re-adding the
  connection (§3 below), not an in-place recovery.
- **A real external database is still not what this document connects to** — the same
  standing limitation `M4-CONN-FE-096`'s manual test names: no permit mechanism exists yet for
  a live connection's destination through the egress proxy. This walkthrough connects to a
  throwaway database inside the `sandbox` container, which `api`/`worker` already reach on the
  `sandbox` Compose network.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env` and confirm every `?set ... in .env` placeholder has a real value. Note the value
of `ASKWELL_RUN_DIR` (defaults to `./.run`) — the install secret lives at
`$ASKWELL_RUN_DIR/install.key` on the host, and you will delete it in §2.

---

## Cold start

### 1. Remove any previous state

```
podman compose down -v
rm -rf "${ASKWELL_RUN_DIR:-./.run}"
```

**You should see:** containers and volumes reported removed. The second command clears any
install secret left over from a previous run, so this walkthrough starts from a genuinely
fresh install.

### 2. Bring the stack up and migrate

```
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** `postgres`, `sandbox`, `redis`, `egress-proxy`, `api`, `worker` all
reported created and started, migration finishing with no error.

### 3. Stand up a database to connect to

```
podman compose exec sandbox psql -U "$(grep ^SANDBOX_POSTGRES_USER .env | cut -d= -f2)" -d postgres <<'SQL'
CREATE DATABASE conn_sec_test OWNER askwell_sandbox_owner;
SQL
```

**You should see:** `CREATE DATABASE`.

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d conn_sec_test <<SQL
CREATE TABLE invoices (id integer primary key, amount numeric);
INSERT INTO invoices VALUES (1, 42.50);
GRANT CONNECT ON DATABASE conn_sec_test TO askwell_sandbox_readonly;
GRANT USAGE ON SCHEMA public TO askwell_sandbox_readonly;
GRANT SELECT ON invoices TO askwell_sandbox_readonly;
SQL
```

**You should see:** `CREATE TABLE`, `INSERT 0 1`, three `GRANT`s.

Note the readonly password:

```
grep ^SANDBOX_READONLY_PASSWORD .env
```

### 4. Open Askwell

`http://127.0.0.1:8000`. **You should see:** the shell load with no alarm banner.

### 5. Navigate to Add a source, by clicking

Click **Library** in the rail, then click **Add a source** in the empty-library card. Click
into the **Connect a database** card. **You should see:** the Engine dropdown and
Host/Port/Database/User/Password fields.

---

## 1. A connection is created with encrypted, not plain, stored configuration

### 6. Connect for real

Engine `PostgreSQL`, Host `sandbox`, Port `5432`, Database `conn_sec_test`, User
`askwell_sandbox_readonly`, Password the value noted in step 3. Click **Connect**.

**You should see:** the form replaced by a **Connected** block naming `conn_sec_test on
sandbox`, then — once introspection finishes (well under a minute for one table) — a
**Ready** block reading "conn_sec_test on sandbox is listed in the library."

### 7. Inspect the stored configuration directly

```
scripts/dev.sh psql
```

```sql
SELECT id, config_encrypted FROM sources WHERE kind = 'connection';
```

**You should see:** one row. `config_encrypted` is a `bytea` whose printed form starts with
`\x6741` (the ASCII bytes `gA` — Fernet's own version marker, base64-encoded) — not `{"engine"`
or anything resembling readable JSON. Confirm neither the password
(the value from step 3) nor the host name `sandbox` appears anywhere in the printed value,
by eye. This is the ticket's own acceptance criterion: "Stored connection configuration is
unreadable without the key."

### 8. Confirm the install secret exists on the host, outside the database

Leave `psql` (`\q`), then on the host:

```
ls -la "${ASKWELL_RUN_DIR:-./.run}/install.key"
```

**You should see:** a file, owner-readable only (mode `600` / `-rw-------`). This is
`Settings.install_secret_path`, generated on first use — it is what makes the ciphertext in
step 7 decryptable at all, and it lives on the host bind mount, not inside the `postgres-data`
volume the database itself uses.

---

## 2. A copied database alone does not yield usable credentials

This step simulates the ticket's own scenario — a stolen laptop's disk, or a database volume
copied without the install secret alongside it — by removing only the key and asking Askwell
to use the connection again.

### 9. Force a re-introspection without the key

```
podman compose down
mv "${ASKWELL_RUN_DIR:-./.run}/install.key" /tmp/install.key.bak
podman compose up -d
```

**You should see:** the stack restart cleanly. The install secret is now absent from
`ASKWELL_RUN_DIR` — standing in for a database volume copied to a second machine with nothing
else brought along.

### 10. Trigger the reindex the same way a user would

Click **Library** in the rail, find `conn_sec_test on sandbox`, and use its reindex action (the
same control any other source's "Reindex" uses).

**You should see:** the source move to an **attention** state within a few seconds, not a
network-failure state. Click into it, or check settings (**Settings** → **Connected
databases**) — the message shown is: "Askwell cannot decrypt this connection's stored
credentials. The key they were encrypted with is missing or has changed — re-enter the
password to reconnect. This is not the same as an unreachable host: the database was never
contacted." **Confirm:** this is a distinct message from `host_unresolved` or
`connection_refused` — the acceptance criterion's own point, that a lost key must not look like
an unreachable host.

### 11. Confirm no socket was even opened

```
podman compose logs worker --tail 30
```

**You should see:** a `connection_introspect_locked` log line for this source's id, and no
line resembling a PostgreSQL connection attempt to `sandbox:5432` for this job — the code path
(`run_introspection`) checks `crypto.decrypt` before `probe_connection` is ever called, so a
locked credential never reaches the network at all.

### 12. Confirm the database row in the sources table

```
scripts/dev.sh psql
```

```sql
SELECT status, last_error FROM sources WHERE kind = 'connection';
```

**You should see:** `status = attention`, `last_error` containing the same "cannot decrypt"
sentence from step 10 — recorded, not just shown transiently in the browser.

`\q` to leave.

### 13. Restore the key and confirm the connection works normally again

```
mv /tmp/install.key.bak "${ASKWELL_RUN_DIR:-./.run}/install.key"
```

Trigger the same reindex action from the library again.

**You should see:** the source return to `ready` — the original install, with its original
key, reads the credential normally, confirming the lock in §9–12 was specific to the missing
key and not a wider regression.

---

## 3. Nothing decryptable ever appears in logs

### 14. Check the API and worker logs across this whole session

```
podman compose logs api worker | grep -i "conn_sec_test\|askwell_sandbox_readonly" 
```

**You should see:** matches only for `connection_added`, `connection_introspected`, and
similar structured log lines that name the source id, engine, host and port — never the
password from step 3, and never a decrypted JSON blob. This is `C8` and the ticket's own
validation rule: "No credential is ever written in the clear, at any point, including in logs
and error messages."

---

## Known gaps

Not defects — deliberately not built by this ticket or an earlier one:

- **No passphrase.** M7's scope. `derive_key(install_secret, passphrase)` exists and folds a
  passphrase into the same HKDF derivation, but nothing in this build calls it with one — every
  key today is derived from the install secret alone.
- **No key rotation or re-encryption.** Losing the install secret locks every existing
  connection permanently; there is no in-place recovery. The only way forward shown in this
  build is deleting the locked connection and adding it again (not exercised above, since §13
  restores the original key instead).
- **No backup/restore flow to test against.** The ticket's own edge case — "a backup restored
  on another machine" — describes the same underlying mechanism this document exercises in
  §2 (a missing key), but M7 owns the actual backup/restore UI and its "credentials require
  re-entry" messaging; this document verifies the underlying lock, not that future surface.
- **No UI affordance to re-enter credentials from the attention state yet.** The library and
  settings screens report `credentials_locked` accurately (§10), but the only recovery path in
  this build is deleting the source and running the connection wizard again — there is no
  "re-enter password" form on the attention card itself.
