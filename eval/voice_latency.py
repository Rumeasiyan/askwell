#!/usr/bin/env python3
"""Measure end-of-speech-to-first-audio latency against the voice phase's
own budget. `M6-PERF-TEST-136`.

    python eval/voice_latency.py --fixture path/to/sample.wav

Drives the real `/voice/ws` channel repeatedly with one fixed audio input,
the way a real spoken turn arrives: audio frames, then an explicit `end`
control message — the moment a real user stops speaking, not a VAD guess
about it, so `speech_ended` (`askwell.voice_channel`) is set from the same
signal this harness sends, and "from end of speech" (this ticket's own
Validation Rule) means the same thing on both sides.

Every stage duration this script reports is the server's own
`stage_breakdown_ms` (`askwell.voice_channel`), delivered as one `timing`
event per turn — never reconstructed from this script's own wall-clock
readings of when a WebSocket frame happened to arrive, which would fold this
machine's own network and scheduling jitter into numbers that are supposed
to describe the voice path, not this harness.

**No audio fixture ships with this repository.** A fixture usable here has
to be real, recognisable speech — Whisper reports `no_speech` on silence or a
synthetic tone, which never reaches generation or synthesis at all — and
Askwell cannot fetch one (C1) or synthesize one (Kokoro's weights are not
present in this environment either, the same gap every voice ticket's own
cold-start walkthrough has already recorded). `--fixture` is therefore a
required argument: record one real short question, 16 kHz mono 16-bit PCM
(`.wav` or headerless `.pcm`), on the machine this actually runs against, and
point this script at it.

**`--profile` names which of `docs/architecture.md` §6's four hardware tiers
this run is measuring, and is required rather than read from the running
server.** `GET /health` reports `Settings.profile` (`askwell.config.Profile`:
`light`/`balanced`/`full`, which selects generation settings) — a different,
non-overlapping vocabulary from the hardware tier this ticket's own budget
table is keyed on (`light`/`standard`/`accelerated`/`workstation`,
`askwell.hardware`/`models_catalog.py`/`docs/build-plan.md` Phase 5/
`web/lib/voice.ts`). `M6-VUI-FE-134` already hit this and deliberately reads
`GET /setup`'s `probe.tier` instead of `/health`'s `profile` for the same
reason; this script follows the same choice, one step more directly, by
calling `askwell.hardware.probe()` itself rather than a second HTTP hop —
correct under "one user, one machine" (`AGENTS.md` §1), since the harness and
the stack it measures are the same machine by construction. What is still
missing is a way to confirm the *server's own* configuration agrees with the
tier being measured, rather than trusting the operator's `--profile` — filed
as issue #466 rather than guessed around here.

Exits non-zero, with no results file written, when the run could not
honestly measure anything — this machine's own hardware probe does not
support the requested tier, or every turn failed — the same "never let an
unmeasured run look like a passing one" rule `eval/bench.py` already carries.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import wave
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import websockets

# Inlined rather than `import eval._bootstrap`: run as `python
# eval/voice_latency.py`, this script's own directory is on `sys.path`, not
# the repository root, so `eval` (and therefore `askwell`) is not importable
# until this runs. Identical to `eval/bench.py`'s own opening.
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _path in (_REPO_ROOT, _REPO_ROOT / "api" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from askwell.config import ConfigurationError, load_settings  # noqa: E402
from askwell.hardware import probe as probe_hardware  # noqa: E402

from eval.runner import current_model_name  # noqa: E402

# The four tiers `docs/architecture.md` §6 and `askwell.hardware.probe`
# both use. Validated against this set rather than accepted as free text, so
# a typo (`"accelerate"`) fails immediately with a clear message instead of
# silently taking the 8s budget and reporting a false pass.
KNOWN_TIERS = ("light", "standard", "accelerated", "workstation")

# `docs/build-plan.md` Phase 5's own budget, and the one mapping
# `web/lib/voice.ts`'s `voiceLatencyBudgetMs` already made: only
# `accelerated` gets 3.5s, every other profile — `standard`, `light`,
# `workstation` and anything unrecognised — gets `standard`'s 8s. Kept as the
# same two numbers rather than inventing a third tier for `workstation`, so
# the budget a user's screen warns against and the budget this harness scores
# against never quietly disagree.
BUDGET_MS_ACCELERATED = 3500.0
BUDGET_MS_STANDARD = 8000.0


def budget_ms(profile: str) -> float:
    return BUDGET_MS_ACCELERATED if profile == "accelerated" else BUDGET_MS_STANDARD


# 16 kHz mono PCM16 little-endian, fixed by `askwell.voice.transcribe`'s own
# docstring — 100ms per frame is small enough that `end` lands promptly after
# the last frame without the harness itself adding a queueing delay worth
# measuring.
SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
FRAME_BYTES = int(SAMPLE_RATE * BYTES_PER_SAMPLE * 0.1)

STAGE_KEYS = ("transcription_ms", "retrieval_ms", "generation_ms", "synthesis_ms", "first_audio_ms")

_DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"

# How long one turn is allowed to take end to end before the harness gives up
# on it — generous even against the worst plausible `light`-profile turn, so
# a genuinely slow answer is recorded as a real (if ugly) number rather than
# indistinguishable from a hang.
TURN_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True, slots=True)
class TurnResult:
    ok: bool
    status: str | None
    breakdown: dict[str, float | None] | None
    error: str | None


def load_fixture(path: Path) -> bytes:
    """Read a fixture as raw 16 kHz mono PCM16LE bytes, from a `.wav` (via
    the header) or a headerless `.pcm`/`.raw` file (assumed already in that
    format — this script has no way to check)."""
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as wav_file:
            if wav_file.getframerate() != SAMPLE_RATE or wav_file.getnchannels() != 1:
                raise ValueError(
                    f"{path} is {wav_file.getframerate()}Hz/{wav_file.getnchannels()}ch; "
                    f"the voice path requires {SAMPLE_RATE}Hz mono (askwell.voice.transcribe)."
                )
            if wav_file.getsampwidth() != BYTES_PER_SAMPLE:
                raise ValueError(f"{path} is not 16-bit PCM.")
            return wav_file.readframes(wav_file.getnframes())
    return path.read_bytes()


async def _read_json_or_bytes(ws: Any) -> tuple[dict[str, Any] | None, bool]:
    message = await ws.recv()
    if isinstance(message, bytes | bytearray):
        return None, True
    parsed: dict[str, Any] = json.loads(message)
    return parsed, False


async def run_turn(url: str, audio: bytes) -> TurnResult:
    try:
        async with asyncio.timeout(TURN_TIMEOUT_SECONDS):
            async with websockets.connect(url, max_size=None) as ws:
                first = json.loads(await ws.recv())
                if first.get("type") != "turn":
                    return TurnResult(False, None, None, f"unexpected first message: {first}")

                for offset in range(0, len(audio), FRAME_BYTES):
                    await ws.send(audio[offset : offset + FRAME_BYTES])
                await ws.send(json.dumps({"type": "end"}))

                breakdown: dict[str, float | None] | None = None
                status: str | None = None
                while status is None:
                    parsed, is_binary = await _read_json_or_bytes(ws)
                    if is_binary or parsed is None:
                        continue
                    if parsed.get("type") == "timing":
                        breakdown = {key: parsed.get(key) for key in STAGE_KEYS}
                    elif parsed.get("type") == "status":
                        status = parsed.get("status")

                if status != "completed":
                    reason = f"turn ended with status {status!r}"
                    return TurnResult(False, status, breakdown, reason)
                if breakdown is None:
                    return TurnResult(False, status, None, "turn completed with no timing event")
                return TurnResult(True, status, breakdown, None)
    except (TimeoutError, OSError, websockets.exceptions.WebSocketException) as error:
        return TurnResult(False, None, None, str(error))


def _median_worst(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    return statistics.median(values), max(values)


def summarize(results: list[TurnResult]) -> dict[str, dict[str, float | None]]:
    """Median and worst case, per stage plus the total, over turns that
    actually completed. A stage some turns never reached (e.g. one turn's
    synthesis failing) is summarized over only the turns that reached it,
    same as any other missing-data case — never treated as a zero."""
    summary: dict[str, dict[str, float | None]] = {}
    for key in STAGE_KEYS:
        values = [
            r.breakdown[key]
            for r in results
            if r.ok and r.breakdown is not None and r.breakdown.get(key) is not None
        ]
        median, worst = _median_worst(values)
        summary[key] = {"median_ms": median, "worst_ms": worst, "n": len(values)}
    return summary


def dominant_stage(summary: dict[str, dict[str, float | None]]) -> str | None:
    """Which attributable stage's median is largest — the ticket's own "a
    miss identifies which stage caused it", read directly off the summary
    rather than left for a person to eyeball a table."""
    attributable = [k for k in STAGE_KEYS if k != "first_audio_ms"]
    scored = [
        (k, summary[k]["median_ms"]) for k in attributable if summary[k]["median_ms"] is not None
    ]
    if not scored:
        return None
    return max(scored, key=lambda pair: pair[1])[0]


def _model_name() -> str | None:
    try:
        settings = load_settings()
    except ConfigurationError:
        return None
    return current_model_name(settings)


async def main_async(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument(
        "--profile",
        required=True,
        choices=KNOWN_TIERS,
        help="which hardware tier this run measures — checked against this machine's own probe",
    )
    parser.add_argument("--host", default="api")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--turns", type=int, default=20)
    parser.add_argument("--results-dir", type=Path, default=_DEFAULT_RESULTS_DIR)
    args = parser.parse_args(argv)

    if args.turns < 2:
        parser.error("--turns must be at least 2 — one warm-up turn, one measured turn")

    profile = args.profile
    probed = probe_hardware()
    if probed.tier != profile:
        print(  # noqa: T201 - a command, talking to a terminal
            f"not measured: this machine probes as the {probed.tier!r} tier "
            f"({probed.expectation}), not {profile!r} — measuring on hardware the "
            f"requested tier does not describe would misrepresent the result.",
            file=sys.stderr,
        )
        return 2

    audio = load_fixture(args.fixture)
    if not audio:
        parser.error(f"{args.fixture} is empty")

    url = f"ws://{args.host}:{args.port}/voice/ws"
    model = _model_name()
    started_at = datetime.now(UTC)

    results: list[TurnResult] = []
    for turn_index in range(args.turns):
        result = await run_turn(url, audio)
        results.append(result)
        label = "warm-up" if turn_index == 0 else f"turn {turn_index}"
        if result.ok and result.breakdown is not None:
            print(f"{label}: first_audio {result.breakdown['first_audio_ms']:.0f}ms")  # noqa: T201
        else:
            print(f"{label}: FAILED — {result.error}", file=sys.stderr)  # noqa: T201

    warmup, steady_state = results[0], results[1:]
    summary = summarize(steady_state)
    failed = sum(1 for r in steady_state if not r.ok)
    budget = budget_ms(profile)
    total_summary = summary["first_audio_ms"]
    passed: bool | None = None
    if total_summary["worst_ms"] is not None:
        passed = total_summary["worst_ms"] <= budget

    report = {
        "profile": profile,
        "model": model,
        "date": started_at.date().isoformat(),
        "started_at": started_at.isoformat(),
        "fixture": str(args.fixture),
        "turns_requested": args.turns,
        "turns_measured": len(steady_state),
        "turns_failed": failed,
        "budget_ms": budget,
        "passed": passed,
        "dominant_stage": dominant_stage(summary) if passed is False else None,
        "warmup": {
            "ok": warmup.ok,
            "breakdown": warmup.breakdown,
            "error": warmup.error,
        },
        "summary": summary,
        "raw_turns": [asdict(r) for r in steady_state],
    }

    args.results_dir.mkdir(parents=True, exist_ok=True)
    stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    out_path = args.results_dir / f"voice-latency-{profile}-{stamp}.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n")

    print(f"\nprofile: {profile}  model: {model or 'unknown'}  budget: {budget:.0f}ms")  # noqa: T201
    for key in STAGE_KEYS:
        stat = summary[key]
        if stat["median_ms"] is None:
            print(f"  {key}: not measured")  # noqa: T201
        else:
            print(  # noqa: T201
                f"  {key}: median {stat['median_ms']:.0f}ms  "
                f"worst {stat['worst_ms']:.0f}ms  (n={stat['n']})"
            )
    if passed is None:
        print("result: NOT MEASURED — every turn failed")  # noqa: T201
    else:
        verdict = "PASS" if passed else f"MISS — dominant stage: {report['dominant_stage']}"
        print(f"result: {verdict}")  # noqa: T201
    print(f"written to {out_path}")  # noqa: T201

    if passed is None:
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
