# Manual test — M9-FIX-SEC-209, placeholder Redis passwords and unreadable licences are refused

**Ticket:** `M9-FIX-SEC-209`, issues #750 and #755. Two things were wrong:

- **Redis accepted the example passwords** (#750). `.env.example` ships the Redis passwords as
  public placeholders (`change-me-redis-api` and two others). Anyone who set Askwell up by copying
  that file by hand, and did not change them, had a Redis that accepted passwords published in
  this repository. Any part of Askwell could then sign in as the API, the only part allowed to
  open a route off the machine. Now Redis refuses to start while any Redis password still starts
  with `change-me`, and names which.
- **The licence check passed licences it could not read** (#755). A dependency that wrote its
  licence as free text, for example `AGPLv3`, `GNU Affero …` or `CC BY-NC 4.0`, passed the
  release licence check. Now any licence the check does not recognise fails it, and a person
  records what the text means.

**Version under test:** `0.7.57`. Run `cat VERSION` and update this line if the version has
moved on.

**Time:** about 20 minutes. **Who can run it:** anyone with a terminal in a checkout of this
repository, Podman installed, and a browser. Most of this test has no screen, and that is the
point: a refusal to start happens before there is a page to show. The browser is used twice, to
see that a refused install shows nothing at all and that a correct one still shows Askwell.

| Piece | File |
| ----- | ---- |
| The refusal | `deploy/redis/start.sh` |
| The known-licence list, and "anything else is unclear" | `KNOWN_LICENSES`, `unclear_tokens` in `api/src/askwell/notices.py` |
| Free text mapped to SPDX, with evidence | `_FREE_TEXT_TO_SPDX` in `scripts/generate_notices.py` |
| The warning a hand-copier reads | the Redis block of `.env.example` |

The automated proof is in `api/tests/test_redis_acl.py` (the `start.sh` refusal tests) and
`api/tests/test_notices.py` (the `M9-FIX-SEC-209` section).

**Your own install is not touched.** Parts A and B start a second, throwaway copy of Askwell
under the project name `askwell209`, reading `.env.example` directly. They never read or change
your `.env`, and the clean-up step removes everything they created. Do not "simulate" the
hand-copy by running `cp .env.example .env`: that overwrites your real passwords.

---

## Part A — a hand-copied `.env.example` does not start

This is what someone who copied `.env.example` by hand, changed nothing, and started Askwell
would do.

1. Open `.env.example` in any text editor and scroll to the Redis block (search for
   `REDIS_API_PASSWORD`).

   **You should see:** three lines whose values start with `change-me-redis-`, and above them a
   comment saying Redis refuses to start while any is still `change-me…`, and to replace all
   three with long random values if you copy this file by hand. Close the editor without saving.

2. From the repository root, start the throwaway copy with the file unchanged:

   ```sh
   podman compose -p askwell209 --env-file .env.example up -d
   ```

   **You should see:** some containers reported `Started`, then
   `dependency failed to start: container askwell209-redis-1 exited (1)`, and the command ends
   with an error. It takes up to a minute.

3. Run `podman logs askwell209-redis-1`.

   **You should see:** these two lines, repeated several times — once for each time Podman
   retried the container before giving up. Nothing else.

   ```
   Refusing to start: still the public placeholder from .env.example: REDIS_API_PASSWORD REDIS_WORKER_PASSWORD REDIS_PROXY_PASSWORD.
   Run the installer, which generates real passwords, or set each to a long random value in .env (C8).
   ```

   All three variable names are listed. No password value is printed.

4. Run `podman compose -p askwell209 --env-file .env.example ps -a`.

   **You should see:** `askwell209-redis-1` stopped, and `askwell209-api-1`,
   `askwell209-worker-1` and `askwell209-egress-proxy-1` in state `created` — they were never
   started, because each waits for a healthy Redis. Postgres, the sandbox, voice and the
   inference bridge may be `running`; they do not use Redis.

5. **Only if your own Askwell is not running** (check: `podman ps` lists no `askwell-api-1`),
   open a browser and go to `http://localhost:8000`.

   **You should see:** the browser's own "Unable to connect" / "This site can't be reached"
   page. There is no Askwell page, because the part that serves it never started. If your own
   Askwell is running, skip this step: that address is answered by your stack, not this one.

6. Clean up: `podman compose -p askwell209 --env-file .env.example down -v`.

   **You should see:** every `askwell209-…` container and the `askwell209_…` volumes and network
   reported `Removed`.

## Part B — one placeholder left behind is named on its own

Someone who replaced two passwords and missed the third.

1. Make a copy with two real passwords and one placeholder, and start only Redis from it:

   ```sh
   sed -e "s/^REDIS_API_PASSWORD=.*/REDIS_API_PASSWORD=$(openssl rand -hex 32)/" \
       -e "s/^REDIS_PROXY_PASSWORD=.*/REDIS_PROXY_PASSWORD=$(openssl rand -hex 32)/" \
       .env.example > /tmp/askwell209.env
   podman compose -p askwell209 --env-file /tmp/askwell209.env up -d --no-deps redis
   ```

   Use `-d`. Without it the command follows Redis restarting forever and does not return.

2. Wait five seconds, then run `podman logs askwell209-redis-1`.

   **You should see:** `Refusing to start: still the public placeholder from .env.example:
   REDIS_WORKER_PASSWORD.`, repeated. It names that one variable and neither of the other two.

3. Clean up:
   `podman compose -p askwell209 --env-file /tmp/askwell209.env down -v && rm /tmp/askwell209.env`.

## Part C — a real install still starts, and Askwell still opens

1. With your own `.env` (written by the installer, or with three long random Redis values), run:

   ```sh
   podman compose up -d --force-recreate --no-deps redis
   podman inspect -f '{{.State.Health.Status}}' askwell-redis-1
   ```

   Repeat the second command until it answers something other than `starting`.

   **You should see:** `healthy`. `podman logs askwell-redis-1` ends with
   `Ready to accept connections tcp`, and contains no `Refusing to start` line.

2. Run `podman compose up -d` so that everything that depends on Redis is running again.

3. Open a browser and go to `http://localhost:8000`. This is the only address you type.

   **You should see:** Askwell's own interface, not a browser error. If the tab title reads
   `Askwell — interface not built`, the interface has not been built on this machine; run
   `scripts/dev.sh web-build && podman compose restart api` and reload. That is a missing build
   step, not a defect of this ticket.

4. Click **Settings** in the left column.

   **You should see:** the Settings screen opens with its sections filled in, not an error panel.
   Askwell answered with real passwords in place, so the refusal only fires on placeholders.

## Part D — the licence gate fails on free-text AGPL

1. Run `scripts/dev.sh notices` once, so `.notices/web-licenses.json` exists.

   **You should see:** it ends with `DISALLOWED OR UNCLEAR LICENCES FOUND — release gate fails:`
   and one line, for `pypdfium2` (#797). That is expected — see Known gaps.

2. Make a copy of that list with one fabricated package added, whose licence is written as free
   text rather than an SPDX identifier, and run the gate against the copy. Both commands run
   inside the API image (the host's own Python is the wrong version for this project):

   ```sh
   scripts/dev.sh run python -c "import json; d=json.load(open('/app/.notices/web-licenses.json')); d['GNU Affero General Public License v3']=[{'name':'fake-affero','versions':['1.0.0']}]; json.dump(d, open('/app/.notices/fake-affero.json','w'))"
   scripts/dev.sh run python /app/scripts/generate_notices.py /app/.notices/fake-affero.json; echo "exit $?"
   ```

   **You should see:** under `DISALLOWED OR UNCLEAR LICENCES FOUND — release gate fails:`, two
   lines — the `pypdfium2` one from step 1, and
   `python/js package 'fake-affero' 1.0.0: unclear licence GNU AFFERO GENERAL PUBLIC LICENSE V3, needs a decision`
   — then `exit 1`. Before this ticket, `fake-affero` passed silently.

3. That run rewrote `NOTICES.md` with the fake package in it. Put it back:

   ```sh
   rm .notices/fake-affero.json && scripts/dev.sh notices; git diff --stat NOTICES.md
   ```

   **You should see:** the gate red on `pypdfium2` alone again, and `git diff --stat NOTICES.md`
   showing no change beyond what your branch already had. Search `NOTICES.md` for `fake-affero`:
   no match.

---

## Known gaps

Deliberately not built. Do not report these as defects of this ticket.

- **Postgres and the sandbox still accept their `change-me` placeholders** (#798). This ticket
  covers Redis only. A copied `.env.example` still cannot start, because Redis stops the API and
  worker — but a hand-copied `.env` with real Redis passwords and placeholder database passwords
  would start.
- **`scripts/dev.sh notices` is red on `pypdfium2`** (#797). Its licence field reads
  `dependency licenses`, which the gate now correctly treats as unreadable. Someone has to review
  its terms against C9 and map the string. That is this ticket working, not failing.
- **A genuinely new permissive licence also fails the gate.** A package declaring, say, a
  well-known permissive licence written in free text that nobody has mapped yet stops the release
  until a person adds the spelling to `_FREE_TEXT_TO_SPDX` with its evidence. That is the
  intended default (#755): an unread licence is a failure to review, never a pass.
- **No screen explains a refused start.** The refusal is only in `podman logs`; the browser just
  cannot connect. The supported path is the installer, which never writes a placeholder, so a
  screen here would only serve people who bypassed it.
- **The installers were not changed.** They already replaced every `change-me*` value; this
  ticket adds the refusal for anyone who did not use them.
