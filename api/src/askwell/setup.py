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
from askwell.probe import PROFILE_SETTING_KEY, PROFILES, ProbeResult, sync_probe_result
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


def _profile_from_probe_result(result: ProbeResult) -> dict[str, object]:
    """The real host probe (`M7-PROBE-DEPLOY-137`), reshaped into the
    `HardwareProfile` fields the welcome screen already reads
    (`M1-LIB-FE-052`) — `tier`/`floor_met`/`expectation` rather than the
    probe's own `profile`/`below_floor`/`reason`, so `StepMachineCheck`
    needed no field-name changes, only the two new ones this ticket adds.
    """
    accelerator = result.accelerator or {}
    vram_gb = accelerator.get("vram_gb")
    return {
        "tier": result.profile,
        "ram_gb": round(result.ram_gb, 1) if result.ram_gb is not None else None,
        "gpu_detected": bool(accelerator.get("present")),
        "vram_gb": vram_gb if isinstance(vram_gb, (int, float)) else None,
        "floor_met": not result.below_floor,
        "expectation": result.reason,
        "source": "host-probe",
        "probe_failed": result.detection_failed,
    }


async def _resolve_profile(session: AsyncSession, settings: Settings) -> dict[str, object]:
    """The profile the welcome screen shows and the model tier it defaults
    to: the real host probe when it has ever run, else the interim
    in-container reading, with any settings override (`askwell.probe`'s
    `POST /probe/override`, `M7-PROBE-FE-138`) applied on top — the same
    resolution `askwell.probe._current_state` performs for `GET /probe`, so
    the two surfaces cannot disagree about which profile is actually live.
    """
    result = await sync_probe_result(session, settings.probe_result_path)
    if result is not None:
        body = _profile_from_probe_result(result)
    else:
        body = probe_hardware().as_dict()
        body["probe_failed"] = False

    override = await get_setting(session, PROFILE_SETTING_KEY)
    if override is not None and override in PROFILES:
        body["tier"] = override

    return body


async def _setup_state(
    session: AsyncSession, manager: ModelDownloadManager, tier: str, settings: Settings
) -> dict[str, object]:
    return {
        "profile": await _resolve_profile(session, settings),
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
        async with factory() as db:
            tier = request.query_params.get("tier")
            if tier is None:
                resolved = await _resolve_profile(db, settings)
                tier = str(resolved["tier"])
            return JSONResponse(await _setup_state(db, manager, tier, settings))

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
        async with session_scope(factory) as db:
            probed = await _resolve_profile(db, settings)
            await record(
                db,
                Store.DECISIONS,
                PROFILE_SELECTED,
                {
                    "tier": body.tier,
                    "probed_tier": probed["tier"],
                    "chosen_by_user": body.tier != probed["tier"],
                    "floor_met": probed["floor_met"],
                    "probe_source": probed["source"],
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
