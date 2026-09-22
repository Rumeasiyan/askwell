#!/usr/bin/env python3
"""Measures the four answer-path budgets (`docs/ux/ask.md` §7) and ingestion
throughput against a realistic corpus, per hardware profile. `M7-PERF-TEST-167`.

    python eval/answer_latency.py --profile accelerated \\
        --corpus-dir /tmp/askwell-perf-corpus --questions-file /tmp/askwell-perf-questions.json

Generate the corpus first with `eval/fixtures/generate_perf_corpus.py`, into a
directory under `ASKWELL_ROOTS_MOUNT` (the only place `POST /roots` will
accept — same rule a real user hits). `--questions-file` is read by this
script itself, not the server, so it must sit somewhere `scripts/dev.sh
answer-latency`'s own container can reach — under the repository (`.run/` is
already mounted) rather than `ASKWELL_ROOTS_MOUNT`, which that container
never mounts and SELinux refuses to read unlabelled besides.

**Every timing this script reports for the four budgets is its own wall
clock**, from the moment it sends `POST /ask` to the moment each named SSE
event arrives at this process — deliberately, unlike `eval/voice_latency.py`,
which reads the server's own `stage_breakdown_ms` instead. The budgets here
are phrased "of submit" (`docs/ux/ask.md` §7) and "within 3 seconds"/"under
20 seconds" in the ticket's own acceptance criteria — both mean what a
person watching the screen experiences, network included, not a component's
internal duration. The **per-stage breakdown** is the opposite case and does
read the server's own numbers: `GET /ask/{message_id}/trace` returns
`messages.trace`'s stored `retrieve`/`compose` steps, each carrying its own
`ms` — attributing *where* time went needs the server's own stage
boundaries, which this script cannot observe from outside.

**`--profile` is required and checked against this machine's own probe**,
the same refusal `eval/voice_latency.py` already makes and the same reason:
measuring `accelerated` hardware and reporting it as `standard` would
misrepresent the result. Only `standard`'s budgets are named in
`docs/ux/ask.md` §7 and the ticket's own acceptance criteria; every other
profile is measured and reported the same way, but its pass/fail line is
left `null` rather than invented against a number the product never stated.

**Cold vs warm** (the ticket's own edge case) means what the ingestion and
query phases each separately call it: ingestion "cold" is this corpus's
first time being embedded on this machine (no throughput history yet for
`askwell.ingest._estimate` to draw on); query "cold" is the first pass over
the question set immediately after that ingestion completes, before the OS
page cache and Postgres shared buffers have seen this corpus's rows more
than once. "Warm" repeats the same question set with nothing else changed.

Exits non-zero, with **no results file written**, when nothing could be
honestly measured — ingestion never drained, or every turn failed. A file
that exists is a claim that something was measured; the two must never
disagree (audit of this ticket, 2026-09-21/22, issue #572).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _path in (_REPO_ROOT, _REPO_ROOT / "api" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from askwell.config import ConfigurationError, load_settings  # noqa: E402
from askwell.hardware import probe as probe_hardware  # noqa: E402
from eval.runner import current_model_name  # noqa: E402
from eval.voice_latency import KNOWN_TIERS  # noqa: E402

# `docs/ux/ask.md` §7 plus the ticket's own acceptance criteria — the only
# budgets the product states anywhere, and only for `standard`.
BUDGET_FIRST_STEP_MS = 400.0
BUDGET_FIRST_TOKEN_MS = 3000.0
BUDGET_FULL_ANSWER_P50_MS = 20_000.0
BUDGET_FULL_ANSWER_P95_MS = 60_000.0
BUDGETED_PROFILE = "standard"

STAGE_KEYS = ("retrieve", "compose")

_DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"

# Generous: a cold-cache turn with a long answer on a slow profile is a
# genuinely slow real number this script should still record, not treat as a
# hang — same reasoning as `eval/voice_latency.py`'s own constant.
TURN_TIMEOUT_SECONDS = 180.0
INGEST_POLL_SECONDS = 1.0
INGEST_TIMEOUT_SECONDS = 3600.0


@dataclass(frozen=True, slots=True)
class TurnResult:
    ok: bool
    question: str
    first_step_ms: float | None
    first_token_ms: float | None
    total_ms: float | None
    stage_ms: dict[str, float | None] | None
    error: str | None


def iter_sse_event_kinds(lines: list[str]) -> list[str]:
    """Every event kind this SSE body actually carried, in arrival order —
    one entry per `event:`/`data:` pair, exactly the pairing `_sse()`
    (`askwell.ask`) writes on the server side.

    Pulled out as a pure function, unlike a `current_kind` variable folded
    into the timing loop below, specifically so it has a unit test: issue
    #572's second finding was `first_token` silently never scoring across
    two real runs, and a desynced `event:`/`data:` pairing is exactly the
    kind of bug a test on real SSE text catches immediately, where a live
    run against a slow model only tells you the end result, never why.
    """
    kinds = []
    kind: str | None = None
    for line in lines:
        if line.startswith("event:"):
            kind = line[len("event:") :].strip()
            continue
        if line.startswith("data:") and kind is not None:
            kinds.append(kind)
            kind = None
    return kinds


async def run_turn(client: httpx.AsyncClient, question: str) -> TurnResult:
    """Send one question, time `step`/`token`/`done` as they actually arrive
    off the wire (`iter_sse_event_kinds`'s pairing, applied line by line as
    they stream rather than after the body is fully buffered — a buffered
    parse can only recover arrival *order*, not arrival *time*), then fetch
    the trace the server wrote for it.

    `message_id` comes straight off the `done` event's own payload — every
    event on this path carries it (`_Turn.emit`, `askwell.ask`) — rather than
    guessed at by querying `messages` for "whatever committed most recently",
    which is what an earlier version of this script did and is exactly the
    kind of fragile-under-concurrency shortcut a client-supplied id avoids.
    """
    submitted_at = time.monotonic()
    first_step_ms: float | None = None
    first_token_ms: float | None = None
    total_ms: float | None = None
    message_id: str | None = None
    try:
        async with asyncio.timeout(TURN_TIMEOUT_SECONDS):
            async with client.stream("POST", "/ask", json={"question": question}) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    return TurnResult(
                        False,
                        question,
                        None,
                        None,
                        None,
                        None,
                        f"HTTP {response.status_code}: {body[:300]!r}",
                    )

                kind: str | None = None
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        kind = line[len("event:") :].strip()
                        continue
                    if not line.startswith("data:") or kind is None:
                        continue
                    now_ms = (time.monotonic() - submitted_at) * 1000
                    if kind == "step" and first_step_ms is None:
                        first_step_ms = now_ms
                    elif kind == "token" and first_token_ms is None:
                        first_token_ms = now_ms
                    elif kind == "done":
                        total_ms = now_ms
                        done_payload = json.loads(line[len("data:") :].strip())
                        message_id = done_payload.get("message_id")
                        break
                    kind = None

            if total_ms is None:
                return TurnResult(
                    False,
                    question,
                    first_step_ms,
                    first_token_ms,
                    None,
                    None,
                    "stream ended with no done event",
                )
            # `Status = Literal["running", "completed", "stopped", "failed"]`
            # (`askwell.ask`) — a `done` event is not itself success. Issue
            # #572's first finding, in spirit: a turn the server marked
            # `failed` still arrives over HTTP 200 with a `done` event, and
            # treating that as `ok=True` is exactly how a real failure (here,
            # the composed prompt exceeding the inference process's own
            # context window on this corpus) would have gone unreported as a
            # silent success rather than a measured turn failure.
            status = done_payload.get("status")
            if status != "completed":
                return TurnResult(
                    False,
                    question,
                    first_step_ms,
                    first_token_ms,
                    None,
                    None,
                    f"turn ended with status {status!r}: {done_payload.get('reason')}",
                )
            stage_ms = await _fetch_trace(client, message_id) if message_id else {}
            return TurnResult(
                True, question, first_step_ms, first_token_ms, total_ms, stage_ms, None
            )
    except (TimeoutError, httpx.HTTPError) as error:
        return TurnResult(False, question, None, None, None, None, str(error))


async def _fetch_trace(client: httpx.AsyncClient, message_id: str) -> dict[str, float | None]:
    response = await client.get(f"/ask/{message_id}/trace")
    if response.status_code != 200:
        return {}
    steps = response.json().get("steps", [])
    stage_ms: dict[str, float | None] = {}
    for step in steps:
        if isinstance(step, dict) and step.get("kind") in STAGE_KEYS:
            stage_ms[step["kind"]] = step.get("ms")
    return stage_ms


async def run_questions(client: httpx.AsyncClient, questions: list[str]) -> list[TurnResult]:
    results = []
    for question in questions:
        result = await run_turn(client, question)
        results.append(result)
        label = "ok" if result.ok else f"FAILED — {result.error}"
        print(  # noqa: T201 - a command, talking to a terminal
            f"  {result.question[:60]!r}: {label}"
            + (f" (total {result.total_ms:.0f}ms)" if result.total_ms is not None else "")
        )
    return results


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(pct * (len(ordered) - 1)))
    return ordered[index]


def summarize_metric(results: list[TurnResult], field: str) -> dict[str, float | None]:
    values = [getattr(r, field) for r in results if r.ok and getattr(r, field) is not None]
    return {
        "p50_ms": statistics.median(values) if values else None,
        "p95_ms": _percentile(values, 0.95) if values else None,
        "n": len(values),
    }


def stage_breakdown(results: list[TurnResult]) -> dict[str, dict[str, float | None]]:
    breakdown: dict[str, dict[str, float | None]] = {}
    for key in STAGE_KEYS:
        values = [
            r.stage_ms[key]
            for r in results
            if r.ok and r.stage_ms is not None and r.stage_ms.get(key) is not None
        ]
        breakdown[key] = {
            "median_ms": statistics.median(values) if values else None,
            "n": len(values),
        }
    return breakdown


def dominant_stage(breakdown: dict[str, dict[str, float | None]]) -> str | None:
    scored = [(k, v["median_ms"]) for k, v in breakdown.items() if v["median_ms"] is not None]
    if not scored:
        return None
    return max(scored, key=lambda pair: pair[1])[0]


def budget_verdict(
    profile: str,
    first_step: dict[str, float | None],
    first_token: dict[str, float | None],
    full_answer: dict[str, float | None],
) -> dict[str, Any]:
    """`null` on every field for a profile the product states no number for —
    `docs/decisions.md`'s own pattern for `Settings.retrieval_score_threshold`
    (state the number, do not invent a bar for it). Only `standard` gets a
    verdict; the ticket's edge case ("a profile the test machine cannot run —
    reported as not measured, never as a pass") applies the same honesty to a
    profile the product simply never budgeted."""
    if profile != BUDGETED_PROFILE:
        return {
            "applicable": False,
            "reason": f"docs/ux/ask.md §7 states no budget for {profile!r}",
        }
    checks = {
        "first_step_label_p95_lte_400ms": (
            first_step["p95_ms"] is not None and first_step["p95_ms"] <= BUDGET_FIRST_STEP_MS
        ),
        "first_token_p50_lte_3000ms": (
            first_token["p50_ms"] is not None and first_token["p50_ms"] <= BUDGET_FIRST_TOKEN_MS
        ),
        "full_answer_p50_lte_20000ms": (
            full_answer["p50_ms"] is not None and full_answer["p50_ms"] <= BUDGET_FULL_ANSWER_P50_MS
        ),
        "full_answer_p95_lte_60000ms": (
            full_answer["p95_ms"] is not None and full_answer["p95_ms"] <= BUDGET_FULL_ANSWER_P95_MS
        ),
    }
    return {"applicable": True, "checks": checks, "passed": all(checks.values())}


# --- ingestion throughput ----------------------------------------------------


async def measure_ingestion(
    client: httpx.AsyncClient, corpus_dir: Path, filenames: list[str]
) -> dict[str, Any]:
    """Adds the corpus through the real `POST /roots` -> `POST /sources` flow
    (the ticket's own "normal add flow", not a database shortcut) and polls
    `GET /ingest` until the queue drains, timing the whole thing against the
    estimate the same endpoint states — so this measurement and the number a
    real user would see are read from the same place.
    """
    folder = str(corpus_dir)
    root_response = await client.post("/roots", json={"path": folder})
    if root_response.status_code not in (200, 201):
        return {"measured": False, "reason": f"POST /roots failed: {root_response.text[:300]}"}

    before = await client.get("/ingest")
    before_snapshot = before.json()
    initial_done = before_snapshot["documents_ingested"]
    stated_estimate = before_snapshot.get("estimate")

    add_response = await client.post("/sources", json={"folder": folder, "files": filenames})
    if add_response.status_code != 201:
        return {"measured": False, "reason": f"POST /sources failed: {add_response.text[:300]}"}

    started_at = time.monotonic()
    deadline = started_at + INGEST_TIMEOUT_SECONDS
    final_snapshot: dict[str, Any] = before_snapshot
    while time.monotonic() < deadline:
        snapshot = (await client.get("/ingest")).json()
        if snapshot["queue_length"] == 0 and (
            snapshot["documents_ingested"] + snapshot["documents_failed"]
            >= initial_done + len(filenames)
        ):
            final_snapshot = snapshot
            break
        await asyncio.sleep(INGEST_POLL_SECONDS)
    else:
        return {
            "measured": False,
            "reason": f"ingestion did not drain within {INGEST_TIMEOUT_SECONDS:.0f}s",
        }

    elapsed_seconds = time.monotonic() - started_at
    docs_done = final_snapshot["documents_ingested"] - initial_done
    after_estimate = (await client.get("/ingest")).json().get("estimate")
    return {
        "measured": True,
        "documents": docs_done,
        "elapsed_seconds": elapsed_seconds,
        "docs_per_second": docs_done / elapsed_seconds if elapsed_seconds > 0 else None,
        "estimate_before": stated_estimate,
        "estimate_after": after_estimate,
        "failed": final_snapshot["documents_failed"],
    }


def _model_name() -> str | None:
    try:
        settings = load_settings()
    except ConfigurationError:
        return None
    return current_model_name(settings)


async def main_async(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--profile", required=True, choices=KNOWN_TIERS)
    parser.add_argument("--corpus-dir", required=True, type=Path)
    parser.add_argument("--questions-file", required=True, type=Path)
    parser.add_argument("--host", default="api")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--turns", type=int, default=8)
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="corpus already ingested on this machine — measure query latency only",
    )
    parser.add_argument("--results-dir", type=Path, default=_DEFAULT_RESULTS_DIR)
    args = parser.parse_args(argv)

    profile = args.profile
    probed = probe_hardware()
    if probed.tier != profile:
        print(  # noqa: T201
            f"not measured: this machine probes as the {probed.tier!r} tier "
            f"({probed.expectation}), not {profile!r} — measuring on hardware the "
            f"requested tier does not describe would misrepresent the result.",
            file=sys.stderr,
        )
        return 2

    all_questions = json.loads(args.questions_file.read_text())
    if not all_questions:
        parser.error(f"{args.questions_file} has no questions")
    turn_count = min(args.turns, len(all_questions))
    questions = [q["question"] for q in all_questions[:turn_count]]

    started_at = datetime.now(UTC)
    ingestion: dict[str, Any] = {"measured": False, "reason": "skipped (--skip-ingest)"}
    model = _model_name()

    base_url = f"http://{args.host}:{args.port}"
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        # `askwell.middleware.local_session`: every non-interface request
        # needs a session cookie already set, and this is the one request
        # shaped like a browser navigation (`GET`, `Accept: text/html`) that
        # gets one issued rather than refused with 401. `httpx.AsyncClient`
        # keeps its own cookie jar, so every request below reuses it.
        await client.get("/", headers={"Accept": "text/html"})

        if not args.skip_ingest:
            filenames = [q["filename"] for q in all_questions]
            print(f"ingesting {len(filenames)} documents from {args.corpus_dir} ...")  # noqa: T201
            ingestion = await measure_ingestion(client, args.corpus_dir, filenames)
            if not ingestion["measured"]:
                print(f"ingestion not measured: {ingestion['reason']}", file=sys.stderr)  # noqa: T201
            else:
                print(  # noqa: T201
                    f"ingestion: {ingestion['documents']} docs in "
                    f"{ingestion['elapsed_seconds']:.1f}s "
                    f"({ingestion['docs_per_second']:.3f} docs/s)"
                )

        print(f"\ncold pass ({len(questions)} questions):")  # noqa: T201
        cold_results = await run_questions(client, questions)
        print(f"\nwarm pass ({len(questions)} questions):")  # noqa: T201
        warm_results = await run_questions(client, questions)

    any_measured = any(r.ok for r in cold_results) or any(r.ok for r in warm_results)
    if not any_measured:
        print("\nresult: NOT MEASURED — every turn failed", file=sys.stderr)  # noqa: T201
        return 2

    report: dict[str, Any] = {
        "profile": profile,
        "model": model,
        "date": started_at.date().isoformat(),
        "started_at": started_at.isoformat(),
        "corpus_dir": str(args.corpus_dir),
        "turns_requested": turn_count,
        "ingestion": ingestion,
        "cold": {},
        "warm": {},
    }
    for name, results in (("cold", cold_results), ("warm", warm_results)):
        first_step = summarize_metric(results, "first_step_ms")
        first_token = summarize_metric(results, "first_token_ms")
        full_answer = summarize_metric(results, "total_ms")
        breakdown = stage_breakdown(results)
        report[name] = {
            "turns_ok": sum(1 for r in results if r.ok),
            "turns_failed": sum(1 for r in results if not r.ok),
            "first_step_ms": first_step,
            "first_token_ms": first_token,
            "full_answer_ms": full_answer,
            "stage_breakdown": breakdown,
            "dominant_stage": dominant_stage(breakdown),
            "budget": budget_verdict(profile, first_step, first_token, full_answer),
            "raw_turns": [asdict(r) for r in results],
        }

    args.results_dir.mkdir(parents=True, exist_ok=True)
    stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    out_path = args.results_dir / f"answer-latency-{profile}-{stamp}.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n")

    print(f"\nprofile: {profile}  model: {model or 'unknown'}")  # noqa: T201
    for name in ("cold", "warm"):
        section = report[name]
        print(f"\n{name}: {section['turns_ok']} ok, {section['turns_failed']} failed")  # noqa: T201
        for metric in ("first_step_ms", "first_token_ms", "full_answer_ms"):
            stat = section[metric]
            if stat["p50_ms"] is None:
                print(f"  {metric}: not measured")  # noqa: T201
            else:
                print(  # noqa: T201
                    f"  {metric}: p50 {stat['p50_ms']:.0f}ms  p95 {stat['p95_ms']:.0f}ms  "
                    f"(n={stat['n']})"
                )
        budget = section["budget"]
        if not budget["applicable"]:
            print(f"  budget: {budget['reason']}")  # noqa: T201
        else:
            verdict = "PASS" if budget["passed"] else "MISS"
            print(f"  budget: {verdict} {budget['checks']}")  # noqa: T201
            if not budget["passed"]:
                print(f"  dominant stage: {section['dominant_stage']}")  # noqa: T201
    print(f"\nwritten to {out_path}")  # noqa: T201
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
