# Manual test — M6-PERF-TEST-136: Measure voice latency against the profile budgets

## What this ticket built

`api/src/askwell/voice_channel.py` gains `VoiceTurn.stage_timings`/`mark()` and six checkpoints
now get marked across the real voice path — `speech_ended`, `transcription_done`,
`retrieval_started`, `generation_started`, `first_sentence_ready`, `first_audio_ready` (marked
in `voice_stt.py` and `voice_tts.py`) — turned into five named millisecond intervals
(`transcription_ms`, `retrieval_ms`, `generation_ms`, `synthesis_ms`, `first_audio_ms`) by the
new pure `stage_breakdown_ms`, and delivered as one `timing` WebSocket event per turn, right
before the turn's closing status. `eval/voice_latency.py` (new, run via `scripts/dev.sh
voice-latency --fixture <path> --profile <tier>`) drives the real `/voice/ws` channel
repeatedly with one fixed audio input — audio frames, then an explicit `end` control message,
matching "from end of speech, as the user experiences it" — discards the first turn as
warm-up (reported separately), and reports median/worst-case per stage against the profile's
own budget (3.5s `accelerated`, 8s everywhere else), writing a JSON record with profile, model
and date to `eval/results/`. `--profile` is checked against `askwell.hardware.probe()` run on
the harness's own machine; a mismatch is reported as **not measured**, never a pass.

**No audio fixture ships with this repository** (the script's own docstring states why: Whisper
reports `no_speech` on silence or a synthetic tone, so a real recording is required). This
walkthrough therefore needs one short recording of real speech, 16 kHz mono 16-bit PCM
(`.wav` or headerless `.pcm`), made on the machine the harness runs against.

**Same known limitation as every voice ticket since `M6-AUDIO-DEPLOY-125`:** Whisper and Kokoro
weights are not present in this environment, so a real turn against this stack fails at
transcription rather than completing — well inside a second, before either budget elapses.
That means the harness here can be shown running and writing an honest result, but that result
will read as **NOT MEASURED** (every turn failed) rather than a PASS/MISS verdict — Part 3 below
covers that explicitly rather than hiding it.

## Prerequisites

- Podman installed, repo cloned, on branch `feat/m6-perf-test-136`.
- `podman compose up -d` — the full stack, not just `api`.
- After pulling code changes: `scripts/dev.sh build-api`, then
  `podman compose up -d --force-recreate api` (`compose restart` reuses the old image).
- A short `.wav` recording of real speech, 16 kHz mono 16-bit PCM, saved somewhere under the
  repo (e.g. `./sample.wav`) so the container's bind mount can see it.

## Part 1 — automated suites, read the output

```
scripts/dev.sh test
```

**What you should see:** the full API suite passes, including
`api/tests/test_voice_timing.py`'s new cases — a mark is first-write-wins, `stage_breakdown_ms`
turns a full set of checkpoints into five intervals that sum correctly (the four attributable
stages add up to `first_audio_ms`), a stage never reached reports `None` rather than a wrong
number, and an empty mark set reports every stage as `None`.

```
scripts/dev.sh run pytest /app/eval/tests -q
```

**What you should see:** `eval/tests/test_voice_latency.py` passes — `accelerated` gets the
3500ms budget and every other named profile (`standard`, `light`, `workstation`) plus an
unrecognised one gets 8000ms; `summarize()` reports correct median/worst/`n` per stage over
turns that completed, excluding a failed turn rather than treating it as a zero;
`dominant_stage()` picks the attributable stage with the largest median, and returns `None`
when nothing was measured; `load_fixture()` reads a 16kHz mono `.wav` correctly, rejects a
44.1kHz one, and reads a headerless `.pcm` file as-is.

## Part 2 — cold start, launch the app and confirm it is reachable

1. With the stack up, open `http://127.0.0.1:8000/` in the browser.
   **What you should see:** the Ask screen loads — the first-run "Ask your own material" card
   if nothing has been added yet, otherwise the composer directly.
2. Click **Settings** in the navigation and read the hardware line.
   **What you should see:** a stated hardware tier (`light`/`standard`/`accelerated`/
   `workstation`) — this is the `--profile` value the harness run below must match, or the
   harness itself will refuse to call it measured.

## Part 3 — run the harness against the real stack

3. In a terminal, run (substituting the tier read in step 2 and the path to your recording):

   ```
   scripts/dev.sh voice-latency --fixture ./sample.wav --profile standard --turns 5
   ```

   **What you should see:** one line per turn printed as it completes — `warm-up: ...` first,
   then `turn 1` through `turn 4` — each either reporting a `first_audio` millisecond figure or
   `FAILED — <reason>`. In this environment (no Whisper/Kokoro weights), expect every turn to
   print `FAILED`.
4. Read the summary block the harness prints at the end.
   **What you should see:** a `profile: ... model: ... budget: ...ms` line naming the profile
   you passed and its budget (8000ms for `standard`), then one line per stage — each reading
   `not measured` (no turn's `timing` event carried that stage, since none completed) — and a
   final `result: NOT MEASURED — every turn failed` line. This is the honest result for this
   environment, not a defect: the ticket's own edge case ("a machine that cannot run the
   accelerated profile — reported as not measured rather than as a pass") is the same
   never-fake-a-pass rule applied here to a different cause of the same outcome.
5. Check the process exit code (`echo $?` immediately after the command).
   **What you should see:** `2`, confirming the harness's own contract — an unmeasurable run
   never exits `0`.
6. Look at the written result file.
   **What you should see:** a new file under `eval/results/`, named
   `voice-latency-standard-<timestamp>.json` (the profile and start time you ran with), and it
   opens as valid JSON containing `"profile"`, `"model"`, `"date"`, `"budget_ms"`,
   `"passed": null`, and a `"summary"` object with every stage's `"n"` at `0`.
7. Re-run step 3 with a profile that does **not** match what Settings reported in step 2, e.g.
   `--profile accelerated` on a machine Settings called `standard`.
   **What you should see:** the harness refuses immediately — a `not measured: this machine
   probes as the 'standard' tier (...), not 'accelerated' — measuring on hardware the requested
   tier does not describe would misrepresent the result.` line on stderr, no turns run, no
   result file written, exit code `2`. This is the profile-mismatch guard this ticket's own
   dependency section (`M6-VUI-FE-134`'s `GET /setup` tier vocabulary) exists to prevent being
   silently violated.

## Part 4 — the felt experience, by hand

8. Back on the Ask screen (step 1), if the first-run card is showing, click **Add a source**,
   add one small `.txt` or `.md` file, and wait for the library to report it `ready`.
9. Press and hold the mic button, say a short sentence, and release.
   **What you should see:** the label cycles "Listening…" → "Transcribing…" and settles on
   "Askwell could not answer that." within about a second — the same transcription failure the
   harness measured in Part 3, now felt directly rather than read off a JSON file. This
   confirms the two views of the same limitation agree: the harness's `NOT MEASURED` result and
   the UI's fast failure are the same underlying cause (no Whisper weights), not two different
   problems.

## What this does not prove

Whether the harness produces a genuine `PASS`/`MISS` verdict with a real per-stage breakdown on
a machine where Whisper and Kokoro weights are actually installed — this environment cannot
exercise that path at all, since every turn fails at transcription before reaching retrieval,
generation or synthesis. Nor does it prove the `accelerated`-tier 3.5s budget is achievable in
practice, or that twenty real turns (the ticket's own recommended run length, reduced to five
here to keep this walkthrough short) produce numbers that don't drift between runs. The
first-turn warm-up figure reported separately in the JSON (`"warmup"`) was not compared against
steady-state numbers here, since steady-state itself was not measurable in this environment.

## Known gaps

- This harness has not been run to completion (a `PASS` or genuine `MISS`) against real
  Whisper/Kokoro weights on any of the four hardware tiers — the open question this ticket
  exists to answer (containerised vs. native transcription) is therefore still open, and stays
  open until someone runs it on a machine with weights installed.
- `--profile` trusts the operator's argument, checked only against this machine's own
  `askwell.hardware.probe()` reading — it cannot confirm the *running server's* configuration
  agrees with the tier being measured. Filed as issue #466, not fixed by this ticket.
- No fixture recording ships with the repository, by design (C1 — nothing here can fetch or
  synthesize one). Every run of this harness requires a person to supply their own.
- Measurement is single-machine and not portable between machines of the same nominal tier, per
  the ticket's own stated known gap — two `standard`-tier machines are not guaranteed to agree.
- Optimisation work that a `MISS` result would motivate is explicitly out of scope for this
  ticket.
