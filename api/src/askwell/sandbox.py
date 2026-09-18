"""The sandbox Postgres instance: isolation for untrusted dumps. C3.

`docs/data-sources.md` §3: a `.sql` dump is a program, and `sqlglot`
(`askwell.sql`, C2) governs *querying* a database, not *loading* one — a dump
that cannot write cannot import, so loading has to be contained a different
way. That way is structural, not a code path that could be bypassed: a
separate Postgres instance (`compose.yaml`'s `sandbox` service, on a network
with no route to Askwell's own database and none to the egress proxy), one
database per imported source, and two fixed roles created once by
`deploy/sandbox/10-roles.sh` — `askwell_sandbox_owner`, which dump content
runs as, and `askwell_sandbox_readonly`, for the query path once loaded.

What actually confines a database to itself is not the roles' identity, it is
PUBLIC's default `CONNECT` privilege — and that has to be revoked on *every*
database this module creates, individually, because `CREATE DATABASE` does
not copy it from a template: `pg_database.datacl` is a shared, cluster-wide
catalog, not part of what a template's file copy carries over, so a freshly
created database's null `datacl` means "the built-in default applies", and
that default is PUBLIC has `CONNECT`. `create_database` revokes it
immediately after creating the database, then grants it back explicitly, only
to the two roles above, only on that one database. `10-roles.sh` revoking the
same privilege on `template1` protects `template1` and `postgres`
specifically — the two databases that exist before this module ever runs —
and is not what protects a database created afterwards.

Importing a dump (`M4-DUMP-ING-088`) and enforcing the size/time cap
(`M4-DUMP-VAL-089`) are not this module's job. This module only ever does two
things to a database: bring one into existence, sealed, or make one stop
existing — and both are decisions records (`docs/audit-log.md` §2), written
here rather than left to whichever caller remembers to, because this is the
one place the guarantee can be made structural instead of conventional.
"""

import asyncio
import re
import uuid
from collections.abc import Sequence

import psycopg
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell import audit
from askwell.logging import get_logger

log = get_logger(__name__)

# Every sandbox database carries this prefix, which is what lets
# `known_databases` tell a sandbox database apart from `postgres` and
# `template1` on the same instance without maintaining a separate list.
PREFIX = "askwell_sbx_"

OWNER_ROLE = "askwell_sandbox_owner"
READONLY_ROLE = "askwell_sandbox_readonly"

_NAME_RE = re.compile(rf"^{re.escape(PREFIX)}[0-9a-f]{{32}}$")


class InvalidSandboxName(RuntimeError):
    """Refused to build SQL from a name that did not come from `generate_name`.

    A Postgres identifier cannot be parameterised the way a value can —
    `CREATE DATABASE $1` is not valid SQL — so every function below builds
    identifiers with `psycopg.sql.Identifier`, which quotes correctly, and
    then this is checked *first*. Nothing in this module ever calls these
    functions with anything but a generated name, but a defence that only
    holds because nothing calls it any other way is not a defence — the same
    reasoning C2 applies to trusting `sqlglot` over a regex.
    """


def generate_name() -> str:
    """A fresh, unpredictable sandbox database name.

    Never accepted from a caller as a plain string — see `InvalidSandboxName`.
    Callers persist the result onto `sources.sandbox_db`.
    """
    return f"{PREFIX}{uuid.uuid4().hex}"


def _validate(name: str) -> None:
    if not _NAME_RE.match(name):
        raise InvalidSandboxName(
            f"{name!r} is not a name generate_name() produced — refusing to build SQL from it."
        )


def _with_database(admin_url: str, database: str) -> str:
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(admin_url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", "", ""))


def _create_database_blocking(admin_url: str, name: str) -> None:
    """The synchronous half of `create_database` — everything but the audit
    record, which needs an `AsyncSession` and has to run on the event loop.

    Two connections, deliberately. `CREATE DATABASE` cannot run inside a
    transaction block and cannot run against the database being created, so
    the first connection stays on the instance's `postgres` maintenance
    database throughout — the same reason `conftest_db.py`'s disposable test
    databases are created that way. The grants that actually matter — the
    schema privileges dump content needs, and the default privileges that
    hand the readonly role visibility into whatever the owner creates — can
    only be set from inside the new database, hence the second connection.
    """
    _validate(name)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        # Not belt-and-suspenders: this is the only thing that revokes
        # PUBLIC's default CONNECT on *this* database. `10-roles.sh` revokes
        # it on `template1`, and `CREATE DATABASE` does not copy that —
        # `pg_database.datacl` is a shared catalog, not part of what a
        # template copies, and a fresh database's null datacl means "the
        # built-in default applies", which is PUBLIC has CONNECT. Verified
        # against a running instance rather than assumed.
        admin.execute(
            sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
        )
        admin.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(
                sql.Identifier(name),
                sql.Identifier(OWNER_ROLE),
                sql.Identifier(READONLY_ROLE),
            )
        )
        admin.execute(
            sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                sql.Identifier(name), sql.Identifier(OWNER_ROLE)
            )
        )

    with psycopg.connect(_with_database(admin_url, name), autocommit=True) as conn:
        conn.execute(sql.SQL("REVOKE ALL ON SCHEMA public FROM PUBLIC"))
        conn.execute(
            sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(sql.Identifier(OWNER_ROLE))
        )
        conn.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(READONLY_ROLE))
        )
        # Whatever the owner creates while loading a dump becomes readable by
        # the readonly role without a second pass once loading finishes —
        # the query path (`docs/data-sources.md` §3, "after loading") depends
        # on this rather than on someone remembering to grant per table.
        conn.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT ON TABLES TO {}"
            ).format(sql.Identifier(OWNER_ROLE), sql.Identifier(READONLY_ROLE))
        )

    log.info("sandbox_database_created", database=name)


async def create_database(session: AsyncSession, admin_url: str, name: str) -> None:
    """Bring a sealed sandbox database into existence, and record the decision.

    C3's own logging requirement — "sandbox database creation and drop are
    decisions records" — is enforced here rather than left to whichever
    caller happens to invoke this, structurally rather than by convention
    (`docs/decisions.md`, issue #322): every path that creates or drops a
    sandbox database goes through this module, so this is the one place the
    guarantee can actually be made to hold. `session` is Askwell's own
    database, not the sandbox instance `admin_url` addresses — two different
    Postgres instances, deliberately (see the module docstring).
    """
    await asyncio.to_thread(_create_database_blocking, admin_url, name)
    await audit.record(
        session, audit.Store.DECISIONS, "sandbox_database_created", {"database": name}
    )


def _drop_database_blocking(admin_url: str, name: str) -> None:
    """The synchronous half of `drop_database` — see `_create_database_blocking`.

    `WITH (FORCE)` closes any connection left open by a crashed import rather
    than refusing with "database is being accessed by other users" — the
    exact situation `reclaim_orphans` exists to clean up.
    """
    _validate(name)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )
    log.info("sandbox_database_dropped", database=name)


async def drop_database(
    session: AsyncSession, admin_url: str, name: str, *, reason: str = "requested"
) -> None:
    """Make a sandbox database stop existing, and record the decision.

    `reason` distinguishes an ordinary drop from `reclaim_orphans`'ing one
    away at startup — both are still exactly one decisions record, not two,
    because they are the same action with a different cause rather than two
    different actions.
    """
    await asyncio.to_thread(_drop_database_blocking, admin_url, name)
    await audit.record(
        session,
        audit.Store.DECISIONS,
        "sandbox_database_dropped",
        {"database": name, "reason": reason},
    )


def known_databases(admin_url: str) -> list[str]:
    """Every sandbox database that currently exists on the instance."""
    with psycopg.connect(admin_url, autocommit=True) as admin:
        rows = admin.execute(
            "SELECT datname FROM pg_database WHERE datname LIKE %s", (f"{PREFIX}%",)
        ).fetchall()
    return [str(row[0]) for row in rows]


async def _live_sandbox_names(session: AsyncSession) -> set[str]:
    """`sources.sandbox_db` for every source that has not been deleted.

    `sources.status` carries the tombstone (`'deleted'`), not a mapped
    `deleted_at` column — see `docs/decisions.md`.
    """
    result = await session.execute(
        text("SELECT sandbox_db FROM sources WHERE sandbox_db IS NOT NULL AND status != 'deleted'")
    )
    return {str(row[0]) for row in result}


async def reclaim_orphans(session: AsyncSession, admin_url: str) -> Sequence[str]:
    """Drop every sandbox database no live source claims.

    Called from `worker.startup`. A database an import created and never
    finished registering — the process was killed between `create_database`
    and the `sources` row committing — is indistinguishable from a source
    that still needs it without this comparison, and left alone it occupies
    the sandbox's own disk budget forever with nothing left that can ever
    drop it.
    """
    known = await asyncio.to_thread(known_databases, admin_url)
    if not known:
        return ()

    live = await _live_sandbox_names(session)
    orphans = sorted(name for name in known if name not in live)

    for name in orphans:
        await drop_database(session, admin_url, name, reason="orphaned_at_startup")

    if orphans:
        log.warning("sandbox_orphans_reclaimed", count=len(orphans), databases=orphans)

    return orphans
