"""The roots registry against a real Postgres.

Three things can only be tested here, and each of them is a promise the ticket
makes rather than an implementation detail.

Nominating a folder is a **decision**, so it appears in the decisions audit
store or it did not happen — the audit write is in the caller's transaction and
takes the registration down with it if it fails.

Removing a root is a **tombstone**. Its sources are still there afterwards, and
they can say why they became unreadable rather than merely being unreadable.
That distinction lives in the schema, not in the code.

And a folder nominated, removed and nominated again has to work, which is a
question about a *partial* unique index and cannot be answered without one.
"""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import roots
from askwell.config import Settings
from askwell.roots import MountState, RootNotFound, RootRefused, SourceState

pytestmark = pytest.mark.requires_db

TABLES = "roots, sources, audit_decisions"


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest_asyncio.fixture
async def session(async_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as opened:
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
        yield opened
        await opened.rollback()
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
    await engine.dispose()


def configured(window: Path | None) -> Settings:
    """Configuration whose only interesting value is the mount window."""
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        roots_mount=window,
    )


async def add_source(session: AsyncSession, root_path: str, name: str = "case files") -> None:
    await session.execute(
        text(
            "INSERT INTO sources (kind, name, root_path, status) "
            "VALUES ('file', :name, :root_path, 'ready')"
        ),
        {"name": name, "root_path": root_path},
    )


async def decisions(session: AsyncSession, kind: str) -> list[dict[str, object]]:
    result = await session.execute(
        text("SELECT payload FROM audit_decisions WHERE kind = :kind ORDER BY occurred_at"),
        {"kind": kind},
    )
    return [row[0] for row in result]


# --- nominating -------------------------------------------------------------


async def test_a_nominated_folder_is_registered_and_readable(
    session: AsyncSession, tmp_path: Path
) -> None:
    clients = tmp_path / "clients"
    clients.mkdir()

    result = await roots.register(session, configured(tmp_path), str(clients))

    assert result.created
    assert result.view.state is MountState.AVAILABLE
    assert result.view.root.path == str(clients)
    assert [item.path for item in await roots.active(session)] == [str(clients)]


async def test_registering_is_a_decision_and_is_recorded_as_one(
    session: AsyncSession, tmp_path: Path
) -> None:
    """A source configuration change. `docs/audit-log.md` §2 puts it here."""
    clients = tmp_path / "clients"
    clients.mkdir()

    await roots.register(session, configured(tmp_path), str(clients))

    recorded = await decisions(session, roots.REGISTERED)
    assert len(recorded) == 1
    assert recorded[0]["path"] == str(clients)


async def test_a_folder_inside_an_existing_root_is_not_registered_twice(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Recognised, and reported as covered rather than as a conflict.

    Files under it can be added, which is the only thing the user was asking
    about. Calling it an error would send them to remove a root they need.
    """
    clients = tmp_path / "clients"
    (clients / "acme").mkdir(parents=True)
    settings = configured(tmp_path)

    await roots.register(session, settings, str(clients))
    nested = await roots.register(session, settings, str(clients / "acme"))

    assert not nested.created
    assert nested.view.root.path == str(clients)
    assert len(await roots.active(session)) == 1


async def test_nominating_the_same_folder_again_changes_nothing(
    session: AsyncSession, tmp_path: Path
) -> None:
    clients = tmp_path / "clients"
    clients.mkdir()
    settings = configured(tmp_path)

    first = await roots.register(session, settings, str(clients))
    again = await roots.register(session, settings, str(clients))

    assert again.created is False
    assert again.view.root.id == first.view.root.id
    assert len(await decisions(session, roots.REGISTERED)) == 1


async def test_a_wider_folder_reports_the_narrower_ones_it_now_covers(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Both stay registered. Two rules that permit the same path permit it once.

    Silently removing a root the user nominated would be a decision taken on
    their behalf, in a list whose whole purpose is that they decide what is in
    it.
    """
    acme = tmp_path / "clients" / "acme"
    acme.mkdir(parents=True)
    settings = configured(tmp_path)

    await roots.register(session, settings, str(acme))
    wider = await roots.register(session, settings, str(tmp_path / "clients"))

    assert wider.created
    assert list(wider.covers) == [str(acme)]
    assert len(await roots.active(session)) == 2


async def test_a_folder_that_is_not_there_is_refused_with_the_reason(
    session: AsyncSession, tmp_path: Path
) -> None:
    with pytest.raises(RootRefused) as refusal:
        await roots.register(session, configured(tmp_path), str(tmp_path / "absent"))
    assert "not there" in str(refusal.value)
    assert await roots.active(session) == []


async def test_a_folder_outside_the_window_is_registered_and_says_what_to_do(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Accepted, not refused, and the difference is the point.

    The only thing wrong with it is a bind mount, which cannot be added to a
    running container. Refusing would make it impossible to nominate anything
    on a fresh install, where no window is configured at all.
    """
    clients = tmp_path / "clients"
    clients.mkdir()

    result = await roots.register(session, configured(None), str(clients))

    assert result.created
    assert result.view.state is MountState.NOT_MOUNTED
    assert result.view.reason is not None
    assert "ASKWELL_ROOTS_MOUNT" in result.view.reason


# --- the check that decides whether a file is read --------------------------


async def test_a_file_under_a_root_has_a_covering_root(
    session: AsyncSession, tmp_path: Path
) -> None:
    clients = tmp_path / "clients"
    clients.mkdir()
    (clients / "contract.pdf").write_bytes(b"%PDF-")
    await roots.register(session, configured(tmp_path), str(clients))

    found = await roots.covering(session, str(clients / "contract.pdf"))
    assert found is not None
    assert found.path == str(clients)


async def test_a_file_outside_every_root_has_none(session: AsyncSession, tmp_path: Path) -> None:
    clients = tmp_path / "clients"
    clients.mkdir()
    await roots.register(session, configured(tmp_path), str(clients))

    assert await roots.covering(session, "/etc/shadow") is None


async def test_a_symlink_cannot_be_used_to_read_outside_a_root(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The escape that a purely lexical check would let through.

    One symlink inside a nominated folder would otherwise stand in for the
    whole disk — the exact permission the user declined to give.
    """
    clients = tmp_path / "clients"
    clients.mkdir()
    outside = tmp_path / "private.txt"
    outside.write_text("not yours", encoding="utf-8")
    (clients / "shortcut.txt").symlink_to(outside)

    await roots.register(session, configured(tmp_path), str(clients))

    assert await roots.covering(session, str(clients / "shortcut.txt")) is None


async def test_a_sibling_folder_sharing_a_prefix_is_not_covered(
    session: AsyncSession, tmp_path: Path
) -> None:
    clients = tmp_path / "clients"
    clients.mkdir()
    (tmp_path / "clients-archive").mkdir()
    await roots.register(session, configured(tmp_path), str(clients))

    assert await roots.covering(session, str(tmp_path / "clients-archive" / "old.pdf")) is None


# --- removing ---------------------------------------------------------------


async def test_removing_a_root_leaves_its_sources_alone(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The promise that has to survive every future edit of this feature.

    Askwell never held a copy of the user's files, and it does not delete the
    record of what it read either.
    """
    clients = tmp_path / "clients"
    clients.mkdir()
    settings = configured(tmp_path)
    registered = await roots.register(session, settings, str(clients))
    await add_source(session, str(clients / "acme"))

    removal = await roots.remove(session, registered.view.root.id)

    assert removal.sources_affected == 1
    assert "nothing is deleted" in str(removal.as_dict()["consequence"])

    surviving = await session.execute(text("SELECT count(*) FROM sources"))
    assert surviving.scalar_one() == 1


async def test_a_removed_root_is_tombstoned_not_deleted(
    session: AsyncSession, tmp_path: Path
) -> None:
    """So that a source under it can say *why*, not merely that it cannot read."""
    clients = tmp_path / "clients"
    clients.mkdir()
    settings = configured(tmp_path)
    registered = await roots.register(session, settings, str(clients))
    await roots.remove(session, registered.view.root.id)

    assert await roots.active(session) == []
    assert [item.path for item in await roots.tombstoned(session)] == [str(clients)]

    state, reason = roots.source_availability(
        str(clients / "acme"),
        await roots.listing(session, settings),
        await roots.tombstoned(session),
    )
    assert state is SourceState.ROOT_REMOVED
    assert "Nothing was deleted" in reason


async def test_removing_is_a_decision_and_is_recorded_as_one(
    session: AsyncSession, tmp_path: Path
) -> None:
    clients = tmp_path / "clients"
    clients.mkdir()
    settings = configured(tmp_path)
    registered = await roots.register(session, settings, str(clients))
    await add_source(session, str(clients / "acme"))
    await roots.remove(session, registered.view.root.id)

    recorded = await decisions(session, roots.REMOVED)
    assert len(recorded) == 1
    assert recorded[0]["sources_affected"] == 1


async def test_the_cost_of_removing_can_be_seen_before_removing(
    session: AsyncSession, tmp_path: Path
) -> None:
    """A confirmation that cannot state the consequence is not a confirmation."""
    clients = tmp_path / "clients"
    clients.mkdir()
    settings = configured(tmp_path)
    registered = await roots.register(session, settings, str(clients))
    await add_source(session, str(clients / "acme"), name="acme")
    await add_source(session, str(clients / "borde"), name="borde")

    preview = await roots.preview_removal(session, registered.view.root.id)

    assert preview.sources_affected == 2
    assert await roots.active(session) != []


async def test_a_folder_can_be_nominated_again_after_being_removed(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The partial unique index, and the reason it is partial.

    A plain unique constraint would refuse this and blame the user for having
    removed the folder earlier.
    """
    clients = tmp_path / "clients"
    clients.mkdir()
    settings = configured(tmp_path)
    first = await roots.register(session, settings, str(clients))
    await roots.remove(session, first.view.root.id)

    again = await roots.register(session, settings, str(clients))

    assert again.created
    assert again.view.root.id != first.view.root.id
    assert len(await roots.tombstoned(session)) == 1


async def test_removing_something_that_is_not_registered_says_so(
    session: AsyncSession,
) -> None:
    with pytest.raises(RootNotFound):
        await roots.remove(session, uuid.uuid4())


async def test_a_source_count_is_not_a_like_pattern(session: AsyncSession, tmp_path: Path) -> None:
    """A folder called `100%_final` is a folder somebody has.

    In a LIKE pattern its `%` and `_` match most of the disk, and the removal
    confirmation would claim it affects sources it has nothing to do with.
    """
    odd = tmp_path / "100%_final"
    odd.mkdir()
    settings = configured(tmp_path)
    registered = await roots.register(session, settings, str(odd))
    await add_source(session, str(odd / "acme"), name="inside")
    await add_source(session, str(tmp_path / "1004final" / "acme"), name="outside")

    preview = await roots.preview_removal(session, registered.view.root.id)
    assert preview.sources_affected == 1
