"""The first-run sequence's own endpoints. `M1-LIB-FE-052`.

Four steps, one module: what the welcome screen needs to check the machine,
acquire the model, and record the two decisions it offers (skip, passphrase).
`docs/ux/first-run.md` is the spec this answers to.

Nothing here blocks on the model. `GET /setup` is cheap and safe to poll
while a 2-9 GB download runs in the background — it reads `ModelDownloadManager`'s
in-memory snapshot, not the file on every call.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.hardware import probe as probe_hardware
from askwell.logging import get_logger
from askwell.model_download import DownloadProgress, ModelDownloadManager, NoDiskSpace
from askwell.settings_store import get_setting, set_setting

log = get_logger(__name__)

_WELCOME_SKIPPED_KEY = "welcome.skipped"
_PASSPHRASE_ENABLED_KEY = "welcome.passphrase_enabled"
_PASSPHRASE_OFFERED_KEY = "welcome.passphrase_offered"

SKIPPED = "welcome_skipped"
PASSPHRASE_DECIDED = "passphrase_decided"
PROFILE_SELECTED = "profile_selected"


class StartModelRequest(BaseModel):
    tier: str


class PassphraseRequest(BaseModel):
    enabled: bool


def _true(value: str | None) -> bool:
    return value == "true"


def _model_dict(manager: ModelDownloadManager, progress: DownloadProgress) -> dict[str, object]:
    body = progress.as_dict()
    body["target_path"] = str(manager.target_path)
    return body


async def _setup_state(
    session: AsyncSession, manager: ModelDownloadManager, tier: str
) -> dict[str, object]:
    return {
        "profile": probe_hardware().as_dict(),
        "model": _model_dict(manager, manager.snapshot(tier)),
        "welcome_skipped": _true(await get_setting(session, _WELCOME_SKIPPED_KEY)),
        "passphrase_offered": _true(await get_setting(session, _PASSPHRASE_OFFERED_KEY)),
    }


def register_setup(
    app: FastAPI,
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """Attach `/setup/*`. Register before the interface catch-all."""
    manager = ModelDownloadManager(settings.inference_model_path)
    app.state.model_download = manager

    @app.get("/setup")
    async def setup_state(request: Request) -> JSONResponse:
        tier = request.query_params.get("tier") or probe_hardware().tier
        async with factory() as db:
            return JSONResponse(await _setup_state(db, manager, tier))

    @app.post("/setup/model/start")
    async def start_model(request: Request, body: StartModelRequest) -> JSONResponse:
        try:
            progress = await manager.start(body.tier)
        except NoDiskSpace as refusal:
            return JSONResponse(
                {
                    "error": "No disk space for the model.",
                    "needed_bytes": refusal.needed_bytes,
                    "free_bytes": refusal.free_bytes,
                },
                status_code=409,
            )

        # After the download actually starts, not before. A request refused for
        # want of disk space selected nothing — writing a decision for it would
        # put a choice in the permanent record that never took effect, and would
        # make a pure refusal path depend on the database.
        #
        # What makes this worth recording is not the tier but the disagreement:
        # whether the user took the machine's own answer or overrode it, and
        # whether they went ahead under the floor after being warned. A year
        # later the question is "why is this slow", and the answer may be that
        # they were told and continued.
        probed = probe_hardware()
        async with session_scope(factory) as db:
            await record(
                db,
                Store.DECISIONS,
                PROFILE_SELECTED,
                {
                    "tier": body.tier,
                    "probed_tier": probed.tier,
                    "chosen_by_user": body.tier != probed.tier,
                    "floor_met": probed.floor_met,
                    "probe_source": probed.source,
                },
            )

        return JSONResponse(_model_dict(manager, progress))

    @app.post("/setup/model/cancel")
    async def cancel_model(request: Request, body: StartModelRequest) -> JSONResponse:
        progress = await manager.cancel(body.tier)
        return JSONResponse(_model_dict(manager, progress))

    @app.post("/setup/model/verify-manual")
    async def verify_manual(request: Request, body: StartModelRequest) -> JSONResponse:
        progress = manager.verify_manual(body.tier)
        return JSONResponse(_model_dict(manager, progress))

    @app.post("/setup/skip")
    async def skip(request: Request) -> JSONResponse:
        async with session_scope(factory) as db:
            await set_setting(db, _WELCOME_SKIPPED_KEY, "true")
            await record(db, Store.DECISIONS, SKIPPED, {})
        log.info("welcome_skipped")
        return JSONResponse({"welcome_skipped": True})

    @app.post("/setup/passphrase")
    async def passphrase(request: Request, body: PassphraseRequest) -> JSONResponse:
        async with session_scope(factory) as db:
            await set_setting(db, _PASSPHRASE_OFFERED_KEY, "true")
            await set_setting(db, _PASSPHRASE_ENABLED_KEY, "true" if body.enabled else "false")
            await record(db, Store.DECISIONS, PASSPHRASE_DECIDED, {"enabled": body.enabled})
        log.info("passphrase_decided", enabled=body.enabled)
        return JSONResponse({"enabled": body.enabled})
