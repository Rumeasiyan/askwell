"""Reads and writes for the `settings` key/value table.

First real consumer of `db.models.Setting` — every earlier ticket that
touches `settings` in prose (`docs/architecture.md` §7) has read it as a
plan, not a table anything writes to yet.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_setting(session: AsyncSession, key: str) -> str | None:
    result = await session.execute(
        text("SELECT value FROM settings WHERE key = :key"), {"key": key}
    )
    row = result.first()
    return None if row is None else str(row[0])


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    await session.execute(
        text(
            "INSERT INTO settings (key, value, updated_at) VALUES (:key, :value, now()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
        ),
        {"key": key, "value": value},
    )
