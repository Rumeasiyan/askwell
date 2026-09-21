# Manual test — M7-OPS-DEPLOY-154a, one shared state volume for `/var/lib/askwell`

**Ticket:** `M7-OPS-DEPLOY-154a` — a named volume mounted at `/var/lib/askwell` on both `api`
and `worker`, so a file one container writes there is visible to the other.
**Version under test:** `0.6.6`.
**Time:** about 5 minutes.
**Who can run it:** anyone with the stack's `.env` — needs `podman compose` and `curl`.

**What is being checked.** `compose.yaml`'s `api` and `worker` services, and the new
`askwell-state` volume. This is infrastructure, not application code — there is no unit test
that can catch a missing mount, because in-process tests run both halves in one Python process
against one `Settings` (#486, #489).

---

## 1. Bring the stack up

```
podman compose up -d
```

**Expect:** `podman compose up -d` output includes `Volume askwell_askwell-state Creating` /
`Created` the first time, and no warning about a `bind` option on a `volume` mount (that
warning means an accidental `:z`/`:Z` suffix crept back onto the mount — named volumes don't
take one).

## 2. Confirm the volume is named, not anonymous

```
podman volume ls | grep askwell-state
```

**Expect:** one line, `askwell_askwell-state` (the compose project prefix plus the name given
in `compose.yaml`). An anonymous volume would show as a bare hash instead, and would not
survive a `podman compose down` without `-v` in the same predictable way.

## 3. Round-trip a file across the container boundary

```
podman compose exec worker sh -c 'mkdir -p /var/lib/askwell/exports && echo hello-from-worker > /var/lib/askwell/exports/roundtrip.txt'
podman compose exec api cat /var/lib/askwell/exports/roundtrip.txt
```

**Expect:** `hello-from-worker`, read back from the `api` container after being written from
`worker`. This is the acceptance criterion in concrete form: the file the worker writes is the
file the API can serve, without either container needing to know about the other's filesystem.

## 4. `/log-budget` no longer 500s

```
curl -s -w '\nHTTP:%{http_code}\n' localhost:8000/log-budget
```

**Expect:** `HTTP:401` (`"No session."` — expected without a browser session cookie, and not
the failure this ticket is about) rather than `HTTP:500`. Before this change, `_free_disk_bytes`
fell back to `settings.trace_dir.parent` (`/var/lib/askwell`) when the `traces` subdirectory
didn't exist yet, and that parent itself did not exist on `api` at all — `shutil.disk_usage`
raised `FileNotFoundError`, which the generic handler turned into a `500` (#486). With the
mount in place, `/var/lib/askwell` exists on both containers before either process runs.

## 5. Survives `podman compose down && up`

```
podman compose down
podman compose up -d
podman compose exec api cat /var/lib/askwell/exports/roundtrip.txt
```

**Expect:** `hello-from-worker` again — the volume is named, so removing and recreating the
containers does not lose it. (`podman compose down -v` would; that is the documented
data-destroying path in `compose.yaml`'s own header comment, not this one.)

## Cleanup

```
podman compose exec worker rm /var/lib/askwell/exports/roundtrip.txt
```

---

## What was checked against the ticket's acceptance criteria

- A named volume mounted at `/var/lib/askwell` on `api` and on `worker` — steps 1–2.
- `export_dir` and `trace_dir` both resolve inside it — step 4 covers `trace_dir` directly
  (the only one of the two that exists in this codebase today; `export_dir` and
  `M7-LOG-BE-155` are explicitly out of scope for this ticket and not yet merged). The mount
  covers the whole `/var/lib/askwell` root, so `export_dir` resolves inside it automatically
  whenever that ticket lands, with no further compose change.
- Survives `podman compose down && up` — step 5.
- Volume empty on first boot, both paths self-create — unchanged behaviour
  (`TraceRing.__init__` already calls `mkdir(parents=True, exist_ok=True)` on first write);
  not re-verified here since nothing about self-creation changed.

## Known gaps

- **`export_dir`/log-export itself was not exercised**, because it does not exist in this
  codebase (`M7-LOG-BE-155` is committed as `wip, not accepted` and not merged) — that is this
  ticket's own stated out-of-scope item, not a defect.
- **A stale `.tmp` from a killed export was not exercised**, for the same reason — nothing
  writes a `.tmp` file under this mount yet.
- **Disk-full degradation was not separately exercised** — unrelated code path
  (`log_budget.measure`'s existing budget staging), not touched by this ticket.
