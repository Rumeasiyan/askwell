"""The host-side hardware probe's result, read into the API. `M7-PROBE-DEPLOY-137`.

The probe itself is `deploy/probe/askwell-probe`, standalone stdlib, for the
same reason `deploy/inference/askwell-inference` is: it must run on the host,
because a container reports the cgroup's or the VM's view of memory rather
than the machine's (`docs/architecture.md` §6), and the host's Python is not
ours to choose. So the seam between the two is a JSON file, the same shape as
`askwell.inference.state` — this module is that seam's other half.

`askwell.hardware.probe()` (`M1-LIB-FE-052`) is a different, deliberately
cruder thing: a same-process, in-container reading good enough for the
welcome screen before this ticket existed, and it stays — it is the fallback
this module defers to when the real probe has never run, exactly as that
module's own docstring already promised it would be.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.hardware import probe as basic_probe
from askwell.settings_store import get_setting, set_setting

# Kept in step with `deploy/probe/askwell-probe`'s own LIGHT/STANDARD/
# ACCELERATED/WORKSTATION constants — that script is standalone stdlib and
# cannot import this module, so a test asserts they have not drifted, the
# same shape as `askwell.inference.state.ProcessState`.
PROFILES = ("light", "standard", "accelerated", "workstation")

PROFILE_PROBED = "profile_probed"
PROFILE_OVERRIDDEN = "profile_overridden"

PROFILE_SETTING_KEY = "hardware.profile"
EVIDENCE_SETTING_KEY = "hardware.probe_evidence"
PROBED_AT_SETTING_KEY = "hardware.probed_at"

REQUEST_FLAG = "probe-rerun-request"

NOT_PROBED_REASON = (
    "The hardware probe has not run yet. It runs on the host, not in a "
    "container — start it with: scripts/dev.sh probe"
)

# An hour, not the inference heartbeat's 35 seconds: this describes RAM and
# an accelerator, which do not change while the machine is running. It exists
# so a result from a previous, different machine (an image copied onto new
# hardware) is shown with a flag rather than trusted silently forever.
STALE_AFTER_SECONDS = 3600.0


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """What the host script measured and selected, as the API sees it."""

    profile: str
    reason: str
    detection_failed: bool
    below_floor: bool
    ram_gb: float | None
    ram_source: str
    cpu: dict[str, Any]
    accelerator: dict[str, Any]
    disk_free_gb: float
    disk_path: str
    platform: str
    probed_at: float

    @property
    def stale(self) -> bool:
        return time.time() - self.probed_at > STALE_AFTER_SECONDS

    def as_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "reason": self.reason,
            "detection_failed": self.detection_failed,
            "below_floor": self.below_floor,
            "ram_gb": self.ram_gb,
            "ram_source": self.ram_source,
            "cpu": self.cpu,
            "accelerator": self.accelerator,
            "disk_free_gb": self.disk_free_gb,
            "disk_path": self.disk_path,
            "platform": self.platform,
            "probed_at": self.probed_at,
            "stale": self.stale,
        }


def read_probe_result(path: Path) -> ProbeResult | None:
    """The host script's last result, or `None` if it has never run.

    `None` rather than a manufactured `standard` guess — that guess already
    exists one layer up, in `askwell.hardware.probe`, which is exactly the
    interim reading M1 shipped so the welcome screen was not blocked on this
    ticket. Inventing a second "we don't know" answer here would leave two,
    disagreeing.

    An unreadable, corrupt, or structurally wrong file reads as absent, never
    as a value — the same rule `askwell.inference.state.read` follows: the
    reassuring answer has to be earned.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("profile") not in PROFILES:
        return None

    ram_gb = payload.get("ram_gb")
    disk_free_gb = payload.get("disk_free_gb")
    probed_at = payload.get("probed_at")
    return ProbeResult(
        profile=str(payload["profile"]),
        reason=str(payload.get("reason", "")),
        detection_failed=bool(payload.get("detection_failed", False)),
        below_floor=bool(payload.get("below_floor", False)),
        ram_gb=float(ram_gb) if isinstance(ram_gb, (int, float)) else None,
        ram_source=str(payload.get("ram_source", "")),
        cpu=dict(payload.get("cpu") or {}),
        accelerator=dict(payload.get("accelerator") or {}),
        disk_free_gb=float(disk_free_gb) if isinstance(disk_free_gb, (int, float)) else 0.0,
        disk_path=str(payload.get("disk_path", "")),
        platform=str(payload.get("platform", "")),
        probed_at=float(probed_at) if isinstance(probed_at, (int, float)) else 0.0,
    )


def _evidence_payload(result: ProbeResult) -> dict[str, object]:
    """Fixed units only.

    `askwell.audit.canonical_payload` refuses floats outright — Postgres
    `jsonb` does not round-trip them identically, and a later verification
    recomputing the hash from the stored value would report tampering that
    never happened. Gigabytes become megabytes as integers, the same pattern
    every other audit payload with a measurement uses.
    """
    accelerator = dict(result.accelerator)
    vram_gb = accelerator.get("vram_gb")
    accelerator["vram_mb"] = round(vram_gb * 1024) if isinstance(vram_gb, (int, float)) else None
    accelerator.pop("vram_gb", None)

    return {
        "profile": result.profile,
        "reason": result.reason,
        "detection_failed": result.detection_failed,
        "below_floor": result.below_floor,
        "ram_mb": round(result.ram_gb * 1024) if result.ram_gb is not None else None,
        "ram_source": result.ram_source,
        "cpu": result.cpu,
        "accelerator": accelerator,
        "disk_free_mb": round(result.disk_free_gb * 1024),
        "platform": result.platform,
    }


async def apply_probe_result(session: AsyncSession, result: ProbeResult) -> None:
    """Record the selection where settings reads it, and the evidence where
    it can be audited later. Not committed here — the caller's transaction.
    """
    await set_setting(session, PROFILE_SETTING_KEY, result.profile)
    await set_setting(session, EVIDENCE_SETTING_KEY, json.dumps(result.as_dict()))
    await set_setting(session, PROBED_AT_SETTING_KEY, repr(result.probed_at))
    await record(session, Store.DECISIONS, PROFILE_PROBED, _evidence_payload(result))


async def sync_probe_result(session: AsyncSession, path: Path) -> ProbeResult | None:
    """Read the host script's latest result and, if it is new, record it.

    "New" is judged by `probed_at` rather than by whether the profile
    changed: a rerun that confirms the same profile is still a selection
    event worth a decisions record, the same way `setup.PROFILE_SELECTED`
    records every explicit choice regardless of whether it altered anything.
    Comparing timestamps rather than recording unconditionally is what keeps
    a settings screen polling `GET /probe` from writing a fresh record on
    every poll.
    """
    result = read_probe_result(path)
    if result is None:
        return None

    applied_at = await get_setting(session, PROBED_AT_SETTING_KEY)
    if applied_at is None or float(applied_at) < result.probed_at:
        await apply_probe_result(session, result)
    return result


def _fallback_probe_body() -> dict[str, object]:
    """The interim in-container reading (`M1-LIB-FE-052`), reshaped into the
    real probe's own field names so `/probe`'s callers — `M7-PROBE-FE-138`'s
    settings control among them — see one shape regardless of which probe
    actually answered. `HardwareProfile.as_dict()` uses `tier`/`floor_met`/
    `expectation`; the real probe uses `profile`/`below_floor`/`reason`. Never
    a `detection_failed` case here — `askwell.hardware.probe()` always
    resolves to some tier, never reports outright failure.
    """
    basic = basic_probe().as_dict()
    return {
        "profile": basic["tier"],
        "reason": f"{NOT_PROBED_REASON} ({basic['expectation']})",
        "detection_failed": False,
        "below_floor": not basic["floor_met"],
        "ram_gb": basic["ram_gb"],
        "ram_source": basic["source"],
        "cpu": {},
        "accelerator": {
            "present": basic["gpu_detected"],
            "kind": None,
            "vram_gb": basic["vram_gb"],
            "source": basic["source"],
        },
        "disk_free_gb": 0.0,
        "disk_path": "",
        "platform": "",
        "probed_at": 0.0,
        "stale": True,
    }


async def _current_state(session: AsyncSession, path: Path) -> dict[str, object]:
    """The real probe's last result, or the interim fallback — either way,
    with any manual override (`POST /probe/override`, `M7-PROBE-FE-138`)
    applied on top and named as such, so the settings screen and the welcome
    screen never disagree about which profile is actually in effect.
    """
    result = await sync_probe_result(session, path)
    if result is not None:
        body = result.as_dict()
        recorded = True
    else:
        # Nothing has ever run the real probe on this machine. Fall back to
        # the interim in-container reading M1 shipped rather than reporting
        # nothing — `docs/architecture.md` §6's own fallback rule, one layer
        # up.
        body = _fallback_probe_body()
        recorded = False

    detected = body["profile"]
    override = await get_setting(session, PROFILE_SETTING_KEY)
    if override is not None and override in PROFILES and override != detected:
        body["profile"] = override
        body["overridden"] = True
        body["detected_profile"] = detected
    else:
        body["overridden"] = False
        body["detected_profile"] = detected

    return {"probe": body, "recorded": recorded}


class OverrideRequest(BaseModel):
    tier: str


class UnknownProfile(ValueError):
    """`body.tier` is not one of `PROFILES`. Never raised for a floor or
    capability mismatch — an override to a profile the machine cannot
    support is permitted (the ticket's own edge case); this only rejects a
    string that is not a profile at all.
    """


async def apply_override(session: AsyncSession, path: Path, tier: str) -> dict[str, object]:
    """The settings profile override (`M7-PROBE-FE-138`): the machine can
    always be told to run at a profile it did not measure into. This never
    refuses on hardware grounds — the consequence (the assistant may fail to
    load, and reports that failure if it does) is the frontend's to state,
    not this function's to enforce.

    Written to the same `hardware.profile` setting the real probe writes, so
    every downstream reader (model selection, voice's latency threshold)
    sees the override without a separate seam. A genuine reprobe still wins
    the next time it runs — `sync_probe_result` overwrites this setting the
    moment a newer probe result lands, which is the "re-run on demand"
    behaviour naming its own reset.
    """
    if tier not in PROFILES:
        raise UnknownProfile(tier)

    state = await _current_state(session, path)
    probe = state["probe"]
    assert isinstance(probe, dict)
    detected = probe["detected_profile"]
    await set_setting(session, PROFILE_SETTING_KEY, tier)
    await record(
        session,
        Store.DECISIONS,
        PROFILE_OVERRIDDEN,
        {"detected": detected, "chosen": tier},
    )
    return await _current_state(session, path)


def register_probe(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Attach `/probe`. `docs/ux/settings.md` §2's "current profile" and
    "re-run" surface.
    """
    result_path = settings.probe_result_path

    @app.get("/probe")
    async def probe_state() -> JSONResponse:
        async with session_scope(factory) as db:
            return JSONResponse(await _current_state(db, result_path))

    @app.post("/probe/override")
    async def probe_override(body: OverrideRequest) -> JSONResponse:
        try:
            async with session_scope(factory) as db:
                return JSONResponse(await apply_override(db, result_path, body.tier))
        except UnknownProfile:
            return JSONResponse(
                {"error": f"{body.tier!r} is not a profile Askwell knows."}, status_code=400
            )

    @app.post("/probe/rerun")
    async def probe_rerun() -> JSONResponse:
        """Ask the host to probe again.

        This container cannot run the probe itself — the same reason the
        probe refuses to run inside a container in the first place. What it
        can do is leave the request where `askwell-probe --watch`, running
        on the host, is polling for it (`scripts/dev.sh probe --watch`), and
        hand back the most recent result immediately; the settings screen
        re-polls `GET /probe` afterwards the way it already does for
        inference.
        """
        (result_path.parent / REQUEST_FLAG).touch()
        async with session_scope(factory) as db:
            return JSONResponse(await _current_state(db, result_path))
