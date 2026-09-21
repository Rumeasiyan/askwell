# Changelog

Notable changes per released version. Newest first. Versions follow `AGENTS.md` §7; the canonical version is in `VERSION`.

Categories: `Added`, `Changed`, `Fixed`, `Removed`, `Security`.

## 0.6.8 - 2026-09-21

`M7-LOG-BE-154` — interaction retention window and prune (`docs/audit-log.md` §8). New
`api/src/askwell/retention.py`: `POST /log-prune` deletes every `audit_interactions` row older
than the configured retention window, in the same transaction as a `interaction_prune`
decisions record naming the cutoff, how many rows were removed, and the hash the interactions
chain now starts from (`first_remaining_prev_hash`) — the same reasoning `M7-LOG-BE-155`'s
windowed export already established for "does not chain to genesis" not being tampering by
itself. `askwell.audit.verify` gained an optional `start_from` parameter for exactly this;
`askwell-verify` looks up the latest prune's boundary and walks the interactions chain from
there instead of the universal genesis value. Pruning is refused (`409`, `export_offered: true`)
unless a **full-history** export (`since` unset) has already covered the range being removed —
`askwell.log_export.run_job` now calls `askwell.retention.mark_exported_through` the moment such
a job completes, and a windowed export never advances that marker. Separately,
`askwell.log_budget.set_retention_months` now refuses (`400`, `confirmation_required: true`) to
shrink the window below the age of the oldest interaction on record unless the caller passes
`confirmed: true`. New migration `20260921_c3a91f5e7d02` grants `askwell_app` `DELETE` on
`audit_interactions` alone — found necessary only by running the finished endpoint against the
live compose stack, since the v1 schema had revoked `DELETE` on both audit tables uniformly and
`pytest -m requires_db`'s own fixtures connect as the table owner, never the restricted role;
`api/tests/test_invariants.py` updated to state the new, narrower boundary explicitly.
`docs/decisions.md`, this date, has the full reasoning. Verified: `pytest -m requires_db` (full
suite, including the chain-survives-a-prune and confirmation-required cases), `scripts/dev.sh
check`-equivalent (lint, format, typecheck, unmarked tests), and a live round trip against the
running compose stack — refusal without export, a full export, a successful prune, and
`askwell-verify` passing against the real chain afterward — after rebuilding the API image and
running the new migration. Issue #512 (`M7-LOG-BE-155`'s missing export-at-budget-limit test)
closed alongside this ticket with a new test in `api/tests/test_log_export.py`. Issue #487
(settings screen prominence for the hard-limit state) re-owned again, not resolved here — it
remains a frontend ticket, and no frontend ticket yet wires either `/log-export` or the new
`/log-prune` into `web/components/settings/storage.tsx`.

## 0.6.7 - 2026-09-21

`M7-LOG-BE-155` — log export as a background job, with the chain and a standalone verifier
(`docs/audit-log.md` §5). `POST /log-export` (optional `since`/`until`, and
`acknowledged_decrypted_export` when a passphrase is set — the export is written in the open,
outside the protection a passphrase gives the library, and refuses with `400` until that is
acknowledged) enqueues an `export_jobs` row and dispatches it to the worker; `GET
/log-export/{id}` reports progress across both audit stores; `GET /log-export/{id}/download`
streams the finished `.zip`. `askwell.log_export.run_job` streams `decisions.jsonl` and
`interactions.jsonl` in keyset-paginated batches (never assembled in memory), each written to
`<name>.jsonl.tmp` and renamed into place only once complete, alongside a `manifest.json`
recording the range and, per store, the `prev_hash` the first exported record actually chains
to — the universal genesis value for an unfiltered export, something else for a windowed one,
which is exactly what lets a date-filtered export verify without expecting the impossible. A
run always deletes and rewrites its working directory from scratch rather than resuming
mid-file, so a crash leaves nothing that reads as a finished file — restartability without a
resumable byte offset. `askwell.log_export_verifier.SOURCE` is the standalone `verify.py`
bundled into every export, a from-scratch reimplementation of `askwell.audit.compute_hash`
with zero `askwell` imports; `api/tests/test_log_export.py` proves the two agree by running
this exact string as a real subprocess, including a tamper test that alters one exported record
and confirms the verifier names the break. Export never calls
`log_budget.enforce_ingestion_allowed` — it is the way out of the limit, not another thing it
blocks — confirmed against the real stack at `budget_bytes=1`. `docs/decisions.md`, this date.
Verified: `pytest -m requires_db` (full suite, including a live subprocess run of the bundled
verifier against a real export and against a deliberately tampered one), `scripts/dev.sh check`
(lint, format, typecheck, unmarked tests), and a live round trip against the running compose
stack — `POST`/`GET /log-export`, download, extract, `verify.py` against the extracted files
and against the `.zip` directly, tamper-and-reverify, and a date-filtered export — after
rebuilding the API image and re-running migrations. New `ExportJob` in `api/src/askwell/db/
models.py` and `ASKWELL_EXPORT_DIR` in `.env.example` (defaults to `/var/lib/askwell/exports`,
the same `askwell-state` volume `M7-OPS-DEPLOY-154a` mounted). Issue #487 (settings screen
prominence for the hard-limit state) re-owned, not resolved here — it is a frontend ticket, and
export existing is only half of what its own Option 1 needs; prune (`M7-LOG-BE-154`) is still
not built.

## 0.6.6 - 2026-09-21

`M7-OPS-DEPLOY-154a` — a named `askwell-state` volume mounted at `/var/lib/askwell` on both
`api` and `worker` in `compose.yaml`. Neither container previously had anything mounted there:
`Settings.trace_dir` (`/var/lib/askwell/traces`) resolved to a path that did not exist at all
on `api`, so `GET /log-budget` 500'd against the real stack every time (#486); the same missing
mount meant a file the worker writes under this root is invisible from the api container's own
filesystem, which is what would have made a log export written by `run_export` undownloadable
had `M7-LOG-BE-155` landed (#489, filed against that ticket's own not-yet-merged work). One
volume covering the whole root rather than a mount per subdirectory, so a future writer under
`/var/lib/askwell` needs no further compose change. Confirmed live against the running,
rebuilt stack: a file written from inside the `worker` container reads back from inside `api`
unchanged, `GET /log-budget` answers `401` (no session) rather than `500`, and the file
survives `podman compose down && up` under the named volume `askwell_askwell-state` (`podman
volume ls`). `docs/manual-tests/M7-OPS-DEPLOY-154a.md`.

## 0.6.5 - 2026-09-21

`M7-SET-FE-147` — the settings screen's privacy and security section (`docs/ux/settings.md`
§4). Three displays: the passphrase control (`web/components/settings/passphrase.tsx`),
surfacing `M7-SEC-BE-151`'s set/change/remove with the no-recovery warning stated next to the
button that sets it, never in a dialog; network activity as a statement, not a toggle
(`web/components/settings/network-activity.tsx`), reading `GET /network`'s live permitted and
refused counts straight from the egress proxy and never substituting zero when the counters
cannot be read; and connected databases (`web/components/settings/connections.tsx`, moved here
from its previous standalone placement), each one read-only by construction since the write
probe (`M4-CONN-SEC-097`) already refuses a write-capable credential before a source is ever
created. No control on this screen pre-authorises egress of any kind, and there is no
web-search setting — `docs/ux/web-search.md` §5 is explicit that a settings toggle is how a
per-question permission becomes a standing one.

## 0.6.4 - 2026-09-21

`M7-SEC-BE-151` — the optional passphrase: set, change, remove and unlock (`docs/ux/settings.md`
§4 and §8). Off by default. Setting one requires acknowledging there is no recovery path, has
never had one, and never will; `askwell.passphrase` folds it into the key derivation
`M4-CONN-SEC-098` already built (`crypto.derive_key(install_secret, passphrase)`), re-encrypting
every stored connection credential in the same transaction so nobody re-enters a single
credential just because a passphrase was added. A wrong passphrase refuses with the same message
regardless of how close it was. Unlock state lives in memory only, for this process alone —
restarting the API locks it again, which is the point, at the cost of the worker process never
being able to unlock at all; filed as its own gap rather than patched (`docs/decisions.md`, this
date). New `GET`/`POST /settings/passphrase*` routes; `askwell.connections` and `askwell.ask`'s
existing decrypt call sites now go through `passphrase.current_key` and raise `Locked` (a
`crypto.CredentialsLocked` subclass) instead of silently decrypting with the wrong key.

## 0.6.3 - 2026-09-21

`M7-SET-FE-148` — settings gains a storage section (`docs/ux/settings.md` §5,
`web/components/settings/storage.tsx`). Per-source index size (approximate: chunk content plus
one embedding vector's worth of float4 lanes per chunk, "unknown" rather than "0" for a
connection/dump source or one still indexing), the log budget's current use with an adjustable
cap, and the interaction retention window (a real, recorded setting — `askwell.log_budget`
gains `get_retention_months`/`set_retention_months`, `GET`/`POST /log-budget/retention` — with no
prune behind it yet). `Usage` gains `configured_bytes` alongside `budget_bytes` (issue #484), so
a cap silently overridden by the 5%-of-free-disk ceiling can be explained rather than merely
observed. Export and prune is a stated, disabled entry point — its backend does not exist yet.
The at-the-limit statement ("ingestion stops first, asking keeps working") is shown plainly,
always.

## 0.6.2 - 2026-09-21

`M7-LOG-BE-153` — log storage budget with staged degradation (`docs/audit-log.md` §3). A new
`askwell.log_budget` measures the interaction store and the trace ring buffer against an
effective budget (the configured cap, or 5% of current free disk if smaller, recomputed on
every check), and exposes three stages: `ok`, `notice` at 80%, and `hard_limit` at or over. `GET`/
`POST /log-budget` read current usage and change the cap — a change is a hash-chained decisions
record, the same shape `askwell.retrieve`'s threshold setting already established. The three
add-source routes (`POST /sources`, `/sources/dump`, `/sources/connection`) now refuse new
ingestion with a 507 once the hard limit is reached, checked after their own validation so a
malformed request is still refused on its own terms without ever touching the database; asking
questions is untouched, since retrieval never calls this check. A stage transition is logged.
Decisions and memory are excluded from the measurement and are never pruned at any budget.

## 0.6.1 - 2026-09-21

`M7-PROBE-FE-138` — the welcome screen and settings now warn and continue instead of refusing.
`GET /setup`'s hardware profile prefers the real host probe (`M7-PROBE-DEPLOY-137`) over the
interim in-container reading whenever it has run, and distinguishes a genuine below-floor reading
(concrete, per-GB expectations, unchanged behaviour) from the probe outright failing to measure
memory (a new `probe_failed` flag) — the welcome screen states each distinctly, naming the
`standard` fallback when detection failed. Settings gains a hardware-profile section
(`web/components/settings/hardware-profile.tsx`) with a manual override: `POST /probe/override`
writes the same `hardware.profile` setting the probe itself writes, states the consequence before
every change ("the assistant will report the failure clearly; document search and indexing keep
working either way"), and records `profile_overridden` as a hash-chained decision alongside the
existing `profile_probed`. A genuine reprobe still wins over an override the next time it runs.
Nothing added here refuses to run on hardware grounds — the ticket's own Validation Rule.

## 0.6.0 - 2026-09-21

M6 ("I can speak to it") completed with `0.5.13`; `docs/BRAIN.md` deferred that milestone's own
`MINOR` bump to the next ticket to land rather than taking it in the same change, so this release
carries it.

`M7-PROBE-DEPLOY-137` — a real host-side hardware probe, replacing the M1 in-container reading as

`M7-PROBE-DEPLOY-137` — a real host-side hardware probe, replacing the M1 in-container reading as
the source of truth. `deploy/probe/askwell-probe` runs on the host, never in a container (a
container reports the cgroup's or the VM's view of memory, not the machine's), measures RAM, CPU,
accelerator and free disk, and selects one of the four `docs/architecture.md` §6 profiles per the
documented thresholds — falling back to `standard` with a stated reason when memory cannot be read
at all, distinct from a genuine reading under the `light` floor, which stays `light` and warns.
Its result crosses to the API over the same host bind mount the inference socket and install key
already use; `askwell.probe.sync_probe_result` records the selection as a `settings` value and a
hash-chained `audit_decisions` record (`profile_probed`) whenever the host has genuinely re-probed,
never on every settings-screen poll. `GET /probe` and `POST /probe/rerun` expose this — reruns are
requested by touching a flag file `askwell-probe --watch` polls for, since a container cannot start
a host process itself. Unrecognised accelerators are reported absent rather than guessed at, Apple
Silicon's unified memory is reported as its own VRAM ceiling, and a VM's memory figure is used as
given with its source stated rather than second-guessed. `askwell.hardware.probe()` (M1) remains
the fallback for a machine the real probe has never run on, exactly as it always promised to be.

## 0.5.13 - 2026-09-21

`M6-STT-FE-129` — low-confidence transcripts are shown and confirmed before Askwell answers
(`docs/ux/voice.md` §5). Issue #468 found the real gap first: nothing between "transcript stored"
and "generation begins" existed to hold a turn for confirmation, so the confirmation had to be
real plumbing, not a client-side stub. `askwell.voice_stt.build_stt_driver` now compares every
`ok` transcript's confidence against the new `stt_confirmation_confidence_threshold` (default
`0.6`); below it, `VoiceTurn.request_confirmation` emits a `confirmation` event and the driver
awaits the future it returns rather than storing anything or calling `on_transcript` — a
confirmed or edited transcript is what gets written to `messages`/`audit_interactions` (`AGENTS.md`
§3 C6), never the unconfirmed one. `askwell.voice_channel._receive_loop` gained `confirm` (proceed
with the transcript as heard) and `edit` (proceed with the client's replacement text, blank edits
ignored) control messages to release it, and a reattaching connection resends the pending
`confirmation` event exactly as it already does for `transcript`/`text`/`confidence`. A held turn
that gets no answer within `stt_confirmation_timeout_seconds` (default 120s) ends unanswered with
nothing stored — the "user walks away" edge case, same shape as `no_speech`. A confident transcript
is untouched: no gate, no added latency. `MicControl` (`web/components/ask/voice-control.tsx`) adds
the `confirming` state: the transcript shown in an editable field with Confirm and Speak again
actions, a local-only confirmation counter (C1), and the transcript staying visible after a
walked-away timeout returns the composer to idle. Resolves issue #468. Commented on issue #460,
re-owning it as still open and unaffected by this ticket — the same in-place `MicControl` tooltip
pattern every prior voice-UI ticket used, not `AskProvider`'s conversation transcript.

## 0.5.12 - 2026-09-21

`M6-VUI-FE-135` — the composer's remaining voice states: microphone permission denied,
non-English speech, and abstention spoken in full (`docs/ux/voice.md` §5). Permission denial is
now read proactively from the Permissions API (`navigator.permissions.query({name:
"microphone"})`, `web/lib/voice.ts`'s `micPermissionReason`) on mount, so voice is shown disabled
with the reason and how to enable it before the mic is ever pressed, without a second
`getUserMedia` prompt — a browser with no Permissions API support for `"microphone"` falls back to
the existing behaviour, learning the same reason from the first real denial. `PermissionStatus.
onchange` clears the block once the browser reports the permission granted, so voice becomes
available again without a reload where the browser supports it. Non-English speech is
`askwell.voice_stt`'s existing `unsupported_language` outcome, now handled by `nextVoiceStatus`'s
previously-missing `language` case, ending the turn with a stated English-only reason rather than
attempting a poor transcription. Abstention needed no backend change — an abstained turn already
speaks `askwell.agent.abstain.compose_abstention`'s own text sentence by sentence, unmodified, the
same as any other answer — but a real display bug is fixed: `statusLabel`'s idle case previously
kept the answer visible only after a *stopped* turn, so any turn that finished normally, an
abstention included, had its full text replaced by the bare "Press and hold to speak" prompt the
instant the turn completed. It now stays shown in full. Commented on issue #460, re-owning it as
still open and unaffected — this ticket renders in `MicControl`'s own tooltip, the same in-place
pattern every prior voice-UI ticket used, not in `AskProvider`'s conversation transcript.

## 0.5.11 - 2026-09-21

`M6-VUI-FE-133` — a stop control, and deliberately no barge-in (`docs/ux/voice.md` §4 #13). A
"Stop" button renders in the composer whenever an answer is generating or being spoken
(`canStop`, true only in the `answering` state) and is the only way out of a running turn —
pressing and holding the mic while one is running still does nothing, unchanged since
`M6-VUI-FE-128a`. Pressing Stop sends `{"type": "stop"}` over the voice socket (mirrored
server-side onto `_Turn.stop_requested`, unchanged since `M6-TTS-BE-130`) and, locally and
immediately, closes the playback `AudioContext` to discard whatever audio is queued or already
playing rather than waiting for the sentence in progress to finish. `startCapture`'s own guard
against speaking over the answer and the new stop guard now share one pure predicate pair
(`canStartCapture`/`canStop`, `web/lib/voice.ts`), closing issue #463 — that guard existed since
`M6-VUI-FE-128a` but had no automated test until it moved into pure, `node:test`-covered code. The
`messages` row is marked partial correctly either way by `askwell.ask`'s existing
`status == "stopped"` check inside the token loop (unchanged, backend not touched by this
ticket); the composer's own post-stop label deliberately says only "Stopped.", never "partial",
because the voice channel's wire protocol has no event letting a client tell "stop cut the
answer off" apart from "stop landed after the text was already complete and only cut off audio"
— filed as issue #471 rather than guessed around. Full reasoning in `docs/decisions.md`.

**Verified**: `scripts/dev.sh web-check` clean (345 tests in `web/lib/voice.test.ts`, 8 new;
typecheck; lint; build; token/contrast/offline guards). `scripts/dev.sh check` clean (891
passed, 1 skipped — backend untouched by this ticket). Cold-start walkthrough against the real,
rebuilt, running stack: the built bundle contains the new `stop_pressed` code
(`grep -o stop_pressed web/out/_next/static/chunks/*.js`); a real `websockets` client against
the real `/voice/ws` sent audio then an explicit `{"type": "stop"}` frame and received a `turn`
event followed by `status: failed` from the real `TranscriptionUnavailable` path (no Whisper
weights in this environment) — the `stop` frame is parsed and handled without the connection
erroring, the same known wall every voice ticket's own walkthrough has hit before generation is
reached. No browser tool was available this session, so the actual click/hold interaction is
verified by `web/lib/voice.test.ts`'s pure-function coverage plus this transport-level exercise,
not end to end in a real browser. Full detail in `docs/BRAIN.md`.

### Added

- `web/lib/voice.ts` — `canStartCapture`, `canStop`, `VOICE_STOPPED_REASON`, the `stop_pressed`
  action on `nextVoiceStatus`.
- `web/lib/voice.test.ts` — 8 new tests for the above.
- `docs/manual-tests/M6-VUI-FE-133.md`.

### Changed

- `web/components/ask/voice-control.tsx` — the Stop button and `handleStop`; `startCapture`'s
  guard now calls `canStartCapture`; `statusLabel` appends the "Stopped." note to a retained
  partial answer rather than replacing it.

## 0.5.10 - 2026-09-21

`M6-VUI-FE-132` — the live level meter and elapsed-time indicator in the composer's mic control, plus the "microphone appears silent" edge case a muted system mic needs (`docs/ux/voice.md` §2, §5). The level is `rmsLevel` of the same capture buffer `onaudioprocess` already downsamples and sends, so the meter costs one more pass over a buffer that already exists rather than a second signal path — updated via `transform: scaleX()` on every buffer (~11/s) rather than `width`, to keep it off the layout thread. A muted mic still delivers real, on-schedule callbacks at or near zero, so silence cannot be told from "not listening" by absence of events: `micAppearsSilent` instead watches how long it has been since a buffer crossed `MIC_LEVEL_SILENCE_THRESHOLD` and swaps the tooltip copy once that exceeds 1.5s, rather than continuing to claim it is listening. Elapsed time is a plain wall-clock diff from capture start on its own 200ms interval, independent of whether any audio arrives, so it keeps counting through silence rather than resetting. Device-follow on mid-session input switching is not special-cased — `getUserMedia` is called with no `deviceId` constraint, and that is left to the browser's own default-device behaviour rather than reimplemented.

Ticket scope asked for a hands-free toggle in addition to push-to-talk; not built. `voice.md` §7 settles push-to-talk as the only v1 mode, and issue #455 already resolved this exact contradiction against the ticket text before this pickup — no VAD-threshold measurement exists to justify revisiting it.

The ticket's own acceptance criteria also require a voice turn's transcript and answer to "render in the conversation exactly as for a typed question." That remains issue #460's scope (`AskProvider`'s `turns` still doesn't receive a voice turn), not this ticket's granularity of "one control, two indicators" — `MicControl` still shows the transcript/answer in its own tooltip, as it has since `M6-VUI-FE-128a`. Issue #454 (this ticket blocked on missing channel plumbing) is resolved and closed: `M6-VUI-FE-128a` landed that plumbing since #454 was filed. #460 is re-owned, noting `M6-VUI-FE-132` as a second dependent alongside `M6-STT-FE-129`.

**Verified**: `scripts/dev.sh web-check` clean (357 tests, 18 new in `web/lib/voice.test.ts`; typecheck; lint; build; `check-tokens`; `contrast`; `check-offline`). `scripts/dev.sh web-build` succeeds, static export unchanged in shape. No live mic/voice-channel walkthrough in this environment — no browser tool available this session and no Whisper/Kokoro weights present (the same known gap every voice ticket so far has carried forward) — so the meter/silence/elapsed wiring is verified by `web/lib/voice.test.ts`'s unit tests against the pure `rmsLevel`/`micAppearsSilent`/`formatElapsed` functions, plus a clean production build, rather than end to end against a real turn.

### Added

- `web/lib/voice.ts` — `rmsLevel`, `MIC_LEVEL_SILENCE_THRESHOLD`, `MIC_SILENCE_WARNING_MS`, `MIC_SILENT_REASON`, `micAppearsSilent`, `formatElapsed`.
- `web/app/globals.css` — `.ask-mic-meter`, `.ask-mic-meter-fill`.
- `web/lib/voice.test.ts` — 18 new tests for the above.

### Changed

- `web/components/ask/voice-control.tsx` — `MicControl` now tracks level, elapsed time and sustained silence via `startMeter`/`stopMeter`, hung off the same event handlers that already own capture start/stop (`onopen`, `stopCapture`, `handleConnectionLost`, `teardownCapture`) rather than an effect keyed on status, to avoid a synchronous-setState-in-effect lint error. The tooltip renders the meter and elapsed time while listening, and swaps in `MIC_SILENT_REASON` once the mic has gone quiet long enough to say so.

## 0.5.9 - 2026-09-21

`M6-PERF-TEST-136` — a repeatable harness measuring end-of-speech-to-first-audio latency against the voice phase's own budget (3.5s `accelerated`, 8s everywhere else), broken down by stage so a miss is attributable. `askwell.voice_channel.VoiceTurn` gained `stage_timings`/`mark()` and six checkpoints are now marked across the real voice path — end of speech, transcription done, retrieval and generation start (read off `askwell.ask`'s own `step` events), first sentence ready, first audio ready — turned into five named millisecond intervals by the new pure `stage_breakdown_ms` and delivered as one `timing` WebSocket event per turn, right before the turn's closing audio sentinel. `eval/voice_latency.py` (new, run via `scripts/dev.sh voice-latency --fixture <path> --profile <tier>`) drives `/voice/ws` repeatedly with one fixed audio input — audio frames, then an explicit `end`, matching "from end of speech, as the user experiences it" — discards the first turn as warm-up (reported separately), and reports median/worst-case per stage against the budget, writing a JSON record with profile, model and date. `--profile` is a required operator argument rather than read from `GET /health` (`Settings.profile` is a different, non-overlapping vocabulary from the hardware tier the budget table is keyed on — `M6-VUI-FE-134` hit the same mismatch already), checked against `askwell.hardware.probe()` run on the harness's own machine; a mismatch is reported as not measured, never a pass. No audio fixture ships with the repository — Whisper reports `no_speech` on anything that is not real speech, and neither fetching one (C1) nor synthesizing one (Kokoro's weights are not present here either) is available in this environment, so `--fixture` is required and the harness was verified end to end against the real, running stack up to the same known wall every prior voice ticket has recorded (`TranscriptionUnavailable`, no Whisper weights on this machine). Filed issue #466 for the deeper gap this ticket's own `--profile` design works around: no live signal today confirms a running server's actual configuration matches the hardware tier an operator claims to be measuring. Full detail in `docs/BRAIN.md`.

**Verified**: `scripts/dev.sh check` clean (891 passed, 1 skipped — 4 new in `api/tests/test_voice_timing.py`). `scripts/dev.sh test-db` clean (1 new in `api/tests/test_voice_tts.py`). `eval/tests/test_voice_latency.py` (9 new, run via `python -m pytest /app/eval/tests/test_voice_latency.py -c /app/eval/pyproject.toml` — `eval/` has no test entry in `scripts/dev.sh` or CI today, same as every other `eval/tests/*` module). Cold-start walkthrough against the real, rebuilt, running stack, no Whisper/Kokoro weights present (C1 forbids fetching them here): `scripts/dev.sh voice-latency --fixture <a 16kHz mono PCM16 wav> --profile standard --turns 2` connected to the real `/voice/ws`, streamed audio, sent `end`, and received `status: failed` from the real `TranscriptionUnavailable` path (`api` logs confirm: "No Whisper small (CTranslate2) file at /models/whisper-small/model.bin") — the harness correctly reported `NOT MEASURED — every turn failed`, exit code 2, with a JSON report recording `profile: standard`, `model: null` (no inference process running either) and the date. The full pass-path (a real transcript reaching generation and synthesis) is unverified in this environment for the same reason every voice ticket's own walkthrough has already recorded.

### Added

- `api/src/askwell/voice_channel.py` — `VoiceTurn.stage_timings`/`mark()`, `stage_breakdown_ms`, the `timing` event kind.
- `eval/voice_latency.py` — the latency measurement harness.
- `scripts/dev.sh voice-latency` — runs the harness against the running stack.
- `api/tests/test_voice_timing.py`, `eval/tests/test_voice_latency.py`.

### Changed

- `api/src/askwell/voice_stt.py` — marks `transcription_done`.
- `api/src/askwell/voice_tts.py` — marks `retrieval_started`/`generation_started`/`first_sentence_ready`/`first_audio_ready`; emits the `timing` event.
- `api/pyproject.toml`/`api/uv.lock` — `websockets` added to the `dev` dependency group (already resolved transitively via `uvicorn[standard]`), for the harness's own WebSocket client.

## 0.5.8 - 2026-09-21

`M6-VUI-FE-134` — the past-latency-budget indicator, only once the budget is genuinely passed. `MicControl` starts an 8s (or 3.5s on an `accelerated` hardware profile) timer at the real end of speech — the button release that ends `stopCapture`, matching what the user experiences as "I'm done talking" — and shows nothing on a healthy turn. The timer is cancelled, and any indicator already showing hidden, the instant the turn's own end arrives first: the first synthesized audio chunk actually playing, the turn completing, the turn failing (its failure message replaces the indicator, per `docs/ux/voice.md` §5), or the connection dropping — so a turn that passes budget and finishes a moment later never flickers. The hardware tier read here is `GET /setup`'s `profile.tier` (`askwell.hardware.probe`'s `light`/`standard`/`accelerated`/`workstation`), deliberately not `/health`'s `profile` field, which is a different axis entirely — the deployment `Profile` enum (`light`/`balanced`/`full`) that selects models. An unrecognised or unread tier falls back to the 8s `standard` budget, stated on the Settings screen. A local, in-memory counter of budget misses is kept for later measurement (C1: never transmitted). Full detail in `docs/BRAIN.md`.

**Verified**: `scripts/dev.sh web-check` clean (328 tests, 4 new; typecheck; lint; build; `check-tokens`; `contrast`; `check-offline`). Cold-start walkthrough against the real, rebuilt, running stack: `/settings` renders the new budget copy; the Ask screen's idle mic control shows no latency text; browser network log confirms `MicControl` calls `GET /setup?tier=standard` once on mount and gets `200`, and the API's own hardware probe on this machine reports `tier=standard` (31 GB RAM, no GPU) — the case this ticket's indicator is keyed off. No live voice turn exercised (Whisper/Kokoro weights are not present in this environment, the same known gap every voice ticket so far has carried forward), so the fade-in/clear/failure-replaces-indicator transitions are verified by `web/lib/voice.test.ts`'s unit tests rather than end to end.

### Added

- `web/lib/voice.ts` — `voiceLatencyBudgetMs`, `VOICE_LATENCY_BUDGET_ACCELERATED_MS`, `VOICE_LATENCY_BUDGET_STANDARD_MS`, `VOICE_LATENCY_COPY`, `recordVoiceLatencyBudgetMiss`, `getVoiceLatencyBudgetMissCount`.
- `web/components/ask/voice-control.tsx` — the latency indicator itself, keyed off end-of-speech and cleared on first audio, turn completion, turn failure, or connection loss.
- `web/app/globals.css` — `.ask-mic-latency`, fading in via an opacity transition rather than snapping.

### Changed

- `web/app/settings/page.tsx` — states the voice latency budget and its unknown-profile fallback.

## 0.5.7 - 2026-09-21

`M6-VUI-FE-128a` — mic capture, the voice socket client, and the composer's base voice states. Replaces the Phase 1 stub: `MicControl` now opens a real `WebSocket` against `askwell.voice_channel`'s `/voice/ws`, captures the microphone with `getUserMedia`, and drives idle/listening/transcribing/answering — the composer states every dependent voice ticket reads and extends. Push-to-talk: holding the button streams 16 kHz mono PCM16 audio, releasing it stops the stream and closes the turn, so "transcribing" is a real local fact rather than a guess ahead of the backend's own pause detection (`M6-STT-BE-128`). Permission denied, no input device, and a connection dropping mid-turn all surface as stated idle reasons, never a stuck `listening`; a second press while transcribing or answering is ignored, not a second socket. Full detail, including what is deliberately deferred and why, in `docs/BRAIN.md`.

**Verified**: `scripts/dev.sh web-check` clean (324 tests, 25 new; typecheck; lint; build; `check-tokens`; `contrast`; `check-offline`). No live browser/microphone walkthrough in this environment — see `docs/BRAIN.md` for what was verified instead.

### Added

- `web/lib/voice.ts` — `nextVoiceStatus`, `parseVoiceEvent`, `voiceSocketUrl`, `downsampleTo16k`, `floatTo16BitPCM`, `encodeAudioFrame`, `pcm16ToFloat32`.
- `web/components/ask/voice-control.tsx` — the real `MicControl`, replacing the disabled stub in `ask-screen.tsx`.

### Changed

- `web/components/ask/ask-screen.tsx` — `MicControl`/`MicIcon` moved to `voice-control.tsx`; the composer's mic button is no longer permanently disabled.
- `web/app/globals.css` — `.ask-mic-control` gained `data-voice-state` styling for listening/transcribing/answering.

## 0.5.6 - 2026-09-20

`M6-TTS-BE-131` — fall back to text when synthesis is unavailable. `askwell.voice_tts._speak_answer` used to let a `/synthesize` failure propagate out of its poll loop, which `askwell.voice_channel._run_driver`'s own broad exception handler then turned into the whole voice turn failing — an answer that had already generated correctly was thrown away over an unrelated model not being loaded. A synthesis failure (`SynthesisUnavailable`/`SynthesisFailed`) is now caught per sentence: the turn's `synthesis_available` flips off, a new `voice` WebSocket event (`{"available": false, "reason": ...}`) tells the screen to show the note `docs/ux/voice.md` §5 asks for, and no further sentence is sent to `/synthesize` for the rest of that turn — deliberately no in-turn retry, since a model that failed to load will not load again a few hundred milliseconds later. Generation and the on-screen text are untouched: token and citation events keep draining exactly as before, so the answer completes normally as text. Availability is tracked across turns via a mapping `build_tts_driver` closes over once and threads through every call — a turn's first failure logs `voice_synthesis_unavailable`, and the next turn's first successful `/synthesize` call logs `voice_synthesis_recovered`, satisfying both the ticket's "availability transitions are logged" requirement and its C1 local-counter analytics line with the same two log lines. Recovery needs no reload: each turn's first synthesis attempt is independent of the turn before it, so a later turn simply succeeds once the service is back.

**Verified**: `scripts/dev.sh check` clean (887 passed, 1 skipped, unaffected). `scripts/dev.sh test-db` clean (660 passed — 13 in `test_voice_tts.py`, 3 new: synthesis unavailable falls back to text with one note and the turn still completes; a mid-answer failure speaks no more but the rest of the answer is still text, with exactly one note rather than one per remaining sentence; and synthesis recovers on the very next turn, sharing one `availability` mapping across two `_speak_answer` calls the way a real driver's two turns would). **Cold-start walkthrough against the real, rebuilt, running stack, no Whisper/Kokoro weights present** (C1 forbids fetching them here): a real `websockets` client against `/voice/ws`, sending silence and an explicit `end`, produced `TranscriptionUnavailable` → `status: failed` before this ticket's own code is ever reached — the same known gap every voice ticket so far has carried forward, since Whisper (not Kokoro) is the first model on the path. This ticket's own new fallback logic is therefore verified only against the real, rebuilt stack's `scripts/dev.sh test-db` run above, not exercised live end to end in this environment.

## 0.5.5 - 2026-09-20

`M6-TTS-BE-130` — sentence-streamed speech synthesis: a transcript now drives a real answer, spoken sentence by sentence as it streams rather than waiting for the whole answer to finish. `api/src/askwell/voice_stt.py`'s `build_stt_driver` gained an `on_transcript` hook — a successfully transcribed turn now continues into generation and speech instead of ending there. New `api/src/askwell/voice_tts.py`'s `build_tts_driver` is the production hook: it builds an `askwell.ask._Turn` and drives `askwell.ask._generate` on it directly (the same "caller builds and drives its own turn" pattern `test_ask_api.py`'s own stop/disconnection tests already use), polling its events the way `askwell.ask._tail` polls for SSE. Every `token` delta forwards verbatim onto the voice turn as `text` (screen unchanged, markers and all); every `citation`/`fact_citation` forwards verbatim too (`VoiceTurn` gained both event kinds plus `emit_citation`/`emit_fact_citation`); and once new `askwell.agent.claims.segment_sentences` reports a completed sentence — marker gone, never read aloud — it is sent to the `voice` container's new `POST /synthesize` (`api/src/askwell/voice/synthesize.py`, mirroring `/transcribe`) and the resulting PCM16 audio is queued for playback, starting speech on the first sentence. Stopping is cooperative: `VoiceTurn.stop_requested` mirrors onto `_Turn.stop_requested`, which `_run_generation`'s own token loop already breaks on promptly, and no further sentence reaches synthesis once seen, even one already sitting complete in the buffer. A trailing, unterminated sentence (the model ran out of tokens) is still spoken as a last best-effort unit rather than dropped.

**Citations are named naturally, resolving issue #447, without a prompt change**: `_natural_reference`/`_spoken_form` (`voice_tts.py`) derive a spoken phrase mechanically from a citation's own `filename` — `"supplier-agreement-2024.pdf"` becomes `"from the supplier agreement 2024"` — added only the first time a document is cited in an answer, never on every repeat marker. Deliberately not a voice-mode prompt instruction: `answer_composition.v1.md` composes the same text every mode renders on screen, so a model taught to phrase sources in prose would leak that into the typed answer too. Reasoning, and what was rejected, in `docs/decisions.md`.

`Settings.voice_kokoro_voice` (default `af_heart`, verified against `hexgrad/Kokoro-82M`'s own `VOICES.md` this date) is the new configuration point for which voice preset speaks; voice/speed selection beyond this default is out of scope.

**Verified**: `scripts/dev.sh check` clean (887 passed, 1 skipped, unaffected; `test-db`: 658 passed, 8 new in `test_voice_tts.py`). **Cold-start walkthrough against the real, rebuilt, running stack, no Kokoro/Whisper weights present** (C1 forbids fetching them here): `voice`'s `/health` reports both `missing`; a direct `POST /synthesize` answered `503` naming Kokoro's missing path rather than crashing; a real `websockets` client against `/voice/ws` produced the same `status: failed` `M6-STT-BE-127`/`-128` already documented (Whisper absent, so generation/synthesis is never reached here) with no new traceback. The generation-and-speech path itself is exercised only against fakes in this environment — the same known gap every voice ticket so far has carried forward.

### Added

- `api/src/askwell/voice_tts.py` — `build_tts_driver`, `_speak_answer`, `SynthesisUnavailable`, `SynthesisFailed`.
- `api/src/askwell/voice/synthesize.py` — `synthesize()`, `SynthesisResult`.
- `POST /synthesize` on the `voice` service.
- `askwell.agent.claims.segment_sentences`, `Sentence`.
- `VoiceTurn.emit_citation`/`emit_fact_citation`; `citation`/`fact_citation` event kinds.
- `build_stt_driver(..., on_transcript=...)`.
- `askwell.config.Settings.voice_kokoro_voice`.

## 0.5.4 - 2026-09-20

`M6-STT-BE-128` — turn detection: a voice turn now closes itself on a pause, not only on the client's own `end`/`stop`. `api/src/askwell/voice/vad.py` (new, runs inside the `voice` container) scores fixed 512-sample (32ms at 16kHz) frames for speech probability against the already-loaded Silero VAD ONNX session — stateless per call, resetting the recurrent state every frame rather than carrying it between calls, so nothing per-turn or per-connection is kept in that container; a new `POST /vad` on `voice/service.py` exposes it, refusing 503 with the missing model's path when no session loaded, the same shape `/transcribe` already uses. `api/src/askwell/voice_turn_detection.py` (new) is the production `TurnDetector`: one instance per connection, fed every audio frame `voice_channel._receive_loop` reads, buffering any remainder short of a full frame into the next call. It tracks whether speech has been heard at all this turn — a pause before any speech is not a pause worth closing on, which is what makes "releasing push-to-talk before speaking" (`docs/ux/voice.md` §5) a silent no-op rather than a spurious close — and how much trailing silence has piled up since the last frame that looked like speech, closing the turn (same sentinel, same `audio_in_closed` guard as an explicit `end`) once that crosses `Settings.voice_vad_pause_ms` (default 700ms). `voice_channel.register_voice_channel` gained a `turn_detector` parameter with the same injection shape as `driver`; its default (`null_turn_detector_factory`) never fires, so a caller that supplies neither gets exactly the pre-ticket behaviour.

**700ms is a reasoned starting point, not a measured one** — no recorded-speech fixtures exist in this environment to tune it against (`AGENTS.md`'s own testing note under this ticket: "if it is unusable, that is the open question being answered", and there is no real hands-free client yet to generate that data). Recorded as a decision, with the reasoning, in `docs/decisions.md`, alongside the choice to score VAD frames statelessly rather than carry Silero's recurrent state across an HTTP boundary.

**Verified**: `scripts/dev.sh check` clean (887 passed, 1 skipped — 35 new, in `test_voice_vad.py`, `test_voice_turn_detection.py`, and additions to `test_voice_service.py`/`test_voice_channel.py`); `scripts/dev.sh test-db` clean (unaffected — this ticket touches no database code). **Cold-start walkthrough against the real, rebuilt, running stack**, no Silero weights present (C1 forbids fetching them here): `voice`'s `/health` still reports transcription/synthesis `missing` with their own paths; `POST /vad` on `voice` answers `503` naming the VAD model's path; a real `websockets` client against `api`'s `/voice/ws`, sending one frame's worth of audio and an explicit `end`, produced a logged `POST http://voice:8090/vad` → `503` → `voice_vad_unavailable` warning → the turn still closed on the client's `end` exactly as before this ticket (VAD absent degrades to no-op, never blocks the transport) → `status: failed` (Whisper also absent, same known gap `M6-STT-BE-127` already carries). The pause-closes-a-turn path itself is covered by `test_voice_channel.py`'s fake detector and `test_voice_turn_detection.py`'s scripted `/vad` responses, not exercised live — real Silero weights are the gap, same shape as Whisper's in the prior ticket.

### Added

- `api/src/askwell/voice/vad.py` — `score_frames()`.
- `POST /vad` on the `voice` service.
- `api/src/askwell/voice_turn_detection.py` — `build_vad_turn_detector`, `null_turn_detector_factory`, the production voice `TurnDetector`.
- `askwell.config.Settings.voice_vad_pause_ms`.
- `register_voice_channel(..., turn_detector=...)`.

## 0.5.3 - 2026-09-20

`M6-STT-BE-127` — English transcription behind the voice channel. `api/src/askwell/voice/transcribe.py` (new, runs inside the `voice` container) turns one complete spoken turn's audio into a transcript, a confidence measure (a duration-weighted average of `exp(avg_logprob)` over Whisper's own segments), or a `no_speech`/`unsupported_language` verdict — non-English audio is identified from `faster-whisper`'s language-ID pass and never decoded further, so "no attempt at another language" holds literally. `voice/service.py` exposes this over a new `POST /transcribe` (503 when no model is loaded, 200 otherwise). `api/src/askwell/voice_stt.py` (new) is the production `TurnDriver` — it buffers a turn's audio, calls `/transcribe` over the `internal` network, and stores the outcome: a `messages` row (role `user`, content the transcript or empty for the unsupported-language case), a new `conversations` row stamped `mode='voice'` when the client gave none, and an `audit_interactions` record (`voice_transcribed`) carrying the confidence and language as integers (percent, since audit payloads cannot carry a float). A turn with no speech, or no audio at all, stores nothing. `voice_channel.py`'s `_Event`/`VoiceTurn` were generalised to carry `confidence`/`language` events alongside the existing `transcript`/`text`, and the WebSocket now accepts an optional `conversation_id` query param.

**Wire format decided here, with no frontend voice code yet to consult**: 16 kHz mono, 16-bit signed PCM, little-endian — Silero VAD's own native input (`M6-STT-BE-128`) and what `faster-whisper` accepts as a raw array with no decoding step, so nothing between capture, VAD and Whisper needs resampling. Recorded in `docs/decisions.md` alongside the other call this ticket made: persisting the transcript now rather than leaving it to `M6-TTS-BE-130`, since this ticket's own Acceptance Criteria requires it and C6 makes an unrecorded interaction a bug.

**Verified**: `scripts/dev.sh check` clean (869 passed, 1 skipped — 15 new, in `test_voice_transcribe.py`, `test_voice_service.py`, `test_voice_stt.py`); `scripts/dev.sh test-db` clean (650 passed, `test_voice_stt.py`'s 7 cases against a real Postgres). **Cold-start walkthrough against the real, rebuilt, running stack** — no Whisper weights present (C1 forbids fetching them here): `voice`'s `/health` reports transcription `missing` with the exact path; `POST /transcribe` on `voice` answers `503` naming the same reason; connecting a real `websockets` client to `api`'s `/voice/ws`, sending audio and an `end` signal, produced `voice_turn_started` → a real `POST http://voice:8090/transcribe` logged on `api` (proving the `internal`-network call reaches `voice` directly, not through `egress-proxy` — `NO_PROXY` on `api` now includes `voice`) → `TranscriptionUnavailable` → `status: failed` delivered over the socket, with nothing written to `messages`. `scripts/verify-localhost-binding.sh` still passes. The `ok`/`no_speech`/`unsupported_language` paths and the confidence measure are covered by `test_voice_transcribe.py`'s and `test_voice_stt.py`'s fakes, not exercised live — real Whisper weights are the known gap, same as `M6-AUDIO-DEPLOY-125`.

### Added

- `api/src/askwell/voice/transcribe.py` — `transcribe()`, `TranscriptionResult`.
- `POST /transcribe` on the `voice` service.
- `api/src/askwell/voice_stt.py` — `build_stt_driver`, the production voice `TurnDriver`.
- `askwell.config.Settings.voice_service_host`.
- `VoiceTurn.confidence`/`language_supported`/`detected_language`/`conversation_id`; `confidence`/`language` WebSocket events; an optional `conversation_id` query param on `/voice/ws`.

## 0.5.2 - 2026-09-20

`M6-AUDIO-API-126` — the bidirectional voice WebSocket transport, mounted on `api` (`/voice/ws`) rather than the `voice` container, since `api` is the only component reachable at all (`docs/architecture.md` §2). `api/src/askwell/voice_channel.py` adds `VoiceTurn`, the audio analogue of `askwell.ask`'s `_Turn`/`_turns`: a turn lives independently of any one connection, keyed by a server-minted `turn_id`, so a dropped connection can reconnect (`?turn_id=...`) and resume rather than restart. `transcript` and `text` are kept as running strings and resent in full on reattach ("the text is complete regardless" — `docs/ux/voice.md` §5); `audio_out` is a bounded queue with no history at all, so a reconnect just keeps draining the same queue from wherever it is — the mechanism that makes "the remaining audio, not from the start" true without any bookkeeping. Backpressure on both directions is a bounded `asyncio.Queue` (`Settings.voice_audio_queue_size`, default 32): a slow client stalls the producer rather than growing memory, and a long spoken question is forwarded chunk by chunk into `audio_in` rather than buffered whole.

**There is no transcription or synthesis behind this channel yet** — `M6-STT-BE-127` and `M6-TTS-BE-130` are what will produce a real transcript and real speech, and `M6-STT-BE-127`'s own acceptance criteria already owns storing the transcript on `messages` and the audit record, so this ticket does neither. `register_voice_channel` takes an injectable `driver`; production runs `_default_driver`, which drains incoming audio and ends the turn the moment the client signals the end of speech, without inventing content — proving the transport rather than the pipeline.

**Verified**: `scripts/dev.sh check` clean (861 passed, 1 skipped, 9 new in `test_voice_channel.py` covering the four event kinds on one connection, reconnect after completion, reconnect mid-synthesis without replaying already-delivered audio, and backpressure on both queues directly). **Cold-start walkthrough against the real, rebuilt, running stack**: connected a real `websockets` client from inside the running `api` container to `ws://127.0.0.1:8000/voice/ws`, sent audio frames and an `end` control message, and received the `turn` id followed by `status: completed`; reconnecting with the same `turn_id` after the first connection closed resumed the same turn and completed identically. `scripts/verify-localhost-binding.sh` still passes — the channel adds no new bound port, riding entirely on `api`'s existing loopback-only listener.

### Added

- `api/src/askwell/voice_channel.py` — `VoiceTurn`, `register_voice_channel`, the `/voice/ws` endpoint.
- `askwell.config.Settings.voice_audio_queue_size` (default `32`).

## 0.5.1 - 2026-09-20

`M6-AUDIO-DEPLOY-125` — the voice container, first ticket of Phase 5's second half. A new `voice` service (`api/src/askwell/voice/`, same image as `api`/`worker`, `askwell-voice` entrypoint) loads Whisper `small` (CTranslate2, via `faster-whisper`), Silero VAD (ONNX, via `onnxruntime` directly) and Kokoro-82M (ONNX, via `kokoro-onnx`) from local files at startup and reports transcription and synthesis health separately on `GET /health` — always `200`, matching `api/src/askwell/health.py`'s own no-aggregate-boolean rule. All three sources, licences and registry-verification dates are recorded in `api/src/askwell/voice/catalog.py`.

Every model path is a local file the container only ever opens; none is fetched at runtime (C1). A missing file does not crash the process — it becomes a `missing` state naming the exact path, mirroring `deploy/inference/askwell-inference`'s own `MODEL_MISSING` handling. `transcription` folds Whisper and VAD into one reported line, since Whisper cannot usefully run without VAD gating the stream ahead of it; `synthesis` is Kokoro alone. Sits on the `internal` network only — no `egress` membership at all, unlike `api` and `worker` — because voice has nothing to reach: `docs/decisions.md` already records that voice never escalates to the web. Model files arrive via a new `ASKWELL_MODELS_DIR` bind mount onto `/models`, read-only, defaulting to the same host directory the native inference supervisor already reads its own three models from.

The WebSocket audio path (`M6-AUDIO-API-126`) and the interface are out of this ticket's scope — nothing can be spoken or transcribed yet, only reported on.

**Verified**: `scripts/dev.sh check` clean (852 passed, 1 skipped, 8 new in `test_voice_models.py`/`test_voice_service.py`). **Cold-start walkthrough against the real, rebuilt, running stack**: `podman compose up -d voice` with no model files present started cleanly and logged `voice_startup` naming both missing models by path; `GET /health` on the running container returned `200` with `transcription`/`synthesis` each `"missing"` and a reason naming the exact path; a socket probe from inside the `voice` container to a public address failed with "Network is unreachable" (`internal` has no route out, so there is nothing for the egress proxy's refusal counter to count); stopping and restarting the `voice` container left the API's own `/health` at `200` throughout, confirming text asking is unaffected by voice being down. Loading real model weights was not exercised — that requires the actual files, which C1 forbids downloading as part of this verification.

### Added

- `api/src/askwell/voice/` — `models.py` (`ModelState`, `ModelHealth`, `VoiceModels`, `load_models`), `service.py` (`create_app`, `askwell-voice` entrypoint), `catalog.py` (verified model sources and licences).
- `askwell.config.Settings` — `voice_whisper_model_path`, `voice_vad_model_path`, `voice_kokoro_model_path`, `voice_kokoro_voices_path`, `voice_host`, `voice_port`.
- `compose.yaml` — `voice` service, `ASKWELL_MODELS_DIR` bind mount.

## 0.5.0 - 2026-09-20

**M5 — it handles harder questions — is complete, 14 of 14.** `M5-TRACE-FE-123` — the trace panel's remaining states: normal, abstention, partial, tool ceiling, failed mid-answer, online backend, and trace unavailable after rotation — was the last ticket in the `TRACE` epic and in the milestone. A question needing both a document lookup and a database query now answers correctly in one turn, with a readable trace of how it happened, in every state that turn can land in.

`web/lib/trace.ts` gains `isFailedTrace`/`failureReason` (`trace.status === "failed"` plus the stored `reason`, already written by `_run_generation` but previously unread on the FE), `isPartialTrace`/`partialUncoveredAspects` (the same `partial_coverage`/`uncovered_aspects` fields `M2-PARTIAL-BE-057` writes onto the trace itself, alongside the `compose` step that already carried them), and `isOnlineBackend` plus an optional `TraceBackend.sent` field — unreachable before M8, since nothing writes `backend.mode: "online"` yet, but the panel is ready for it. `trace-panel.tsx`'s `TraceBody` renders a failed trace's steps followed by the error (`--alarm`, per `design-system.md`'s own token table — not `--muted`, which `ask-screen.tsx` uses inconsistently; filed as issue #436, out of this ticket's scope), and a partial trace's uncovered aspects in the same "Not covered by your files" block the answer body's own `UncoveredBlock` already uses. The trace-unavailable state (`trace_rotated`) was already built by `M5-TRACE-FE-119`; this ticket adds a test asserting the edge case that citations cannot rotate with it, since `hitCitation`'s signature never takes a `TraceData` at all — a rotated trace has nothing to lose a citation from.

**Verified**: `scripts/dev.sh check` clean (842 passed, 1 skipped, no backend change); `scripts/dev.sh web-check` clean (299 tests, 13 new in `web/lib/trace.test.ts` covering all seven states plus the citation/rotation invariant). No browser available in this session — the new failed/partial/online-backend branches are verified at the unit level and by reading the render wiring, not by an interactive click-through; the online-backend state remains unreachable until M8 regardless.

### Added

- `web/lib/trace.ts` — `isFailedTrace`, `failureReason`, `isPartialTrace`, `partialUncoveredAspects`, `isOnlineBackend`, `TraceBackend.sent`.
- `web/components/ask/trace-panel.tsx` — `FailedNote`, `PartialNote`; `BackendLine` gains a "what was sent" disclosure for the online backend.

## 0.4.39 - 2026-09-20

`M5-TRACE-FE-122` — threshold adjustment from an abstention trace, with the consequence stated. The last ticket in the `TRACE` epic.

The retrieval threshold becomes a real, runtime-adjustable setting for the first time: `askwell.retrieve.get_retrieval_threshold`/`set_retrieval_threshold` read and write an override in the `settings` table (the same shape `askwell.clarify`'s clarification cap already established), with `Settings.retrieval_score_threshold` staying the shipped default a fresh install starts from. `set_retrieval_threshold` is the only way the value changes, and it always writes an `audit_decisions` record (`retrieval_threshold_changed`) with the old and new value — never automatic, never a side effect of anything else. New `GET`/`POST /settings/retrieval-threshold` (`askwell.retrieve.register_retrieval_threshold`) is the one endpoint pair both surfaces below use.

The abstention trace panel offers `RetrievalThresholdControl` (`web/components/settings/retrieval-threshold.tsx`) only when `lib/retrieval-threshold.ts`'s new `nearMiss()` finds one — an abstention whose `abstain` step says `below_threshold` and whose `retrieve` step actually has a hit, never for `empty_corpus`/`source_indexing`, where loosening the threshold would not have helped. The control states the consequence with the real scores ("The closest passage scored 0.61, just under the 0.65 threshold...") and a number field plus an explicit "Change threshold" button — deliberately not a slider, so a change is a submitted decision rather than a value that drifted while dragging. The same component, same warning copy, is now also reachable from the settings screen's new "Retrieval threshold" section, without the near-miss sentence.

**Verified**: `scripts/dev.sh check` clean (842 passed, 1 skipped — this ticket adds no new `api/tests/` case outside the `requires_db` file below); `scripts/dev.sh test-db` clean (644 passed, 4 new in `api/tests/test_retrieve_records.py`: the threshold defaults to the configured value, a stored override is read back and used by `retrieve()`, changing it writes a decisions record with the old and new value, and a value outside `[0, 1]` is rejected); `scripts/dev.sh web-check` clean (290 tests, 5 new in `web/lib/retrieval-threshold.test.ts` covering `nearMiss()`'s five cases). **Cold-start walkthrough run against the real, rebuilt, running stack**: `GET /settings/retrieval-threshold` returned the default `0.65`; `POST` to `0.5` was read back as `0.5` immediately; `POST` with `1.5` was rejected `422`; `audit_decisions` recorded `{"previous": "0.65", "new": "0.5"}`; `askwell-verify` confirmed the chain intact both with the test record present and after removing it (the tail of the chain, safe to remove without leaving a gap). No browser available in this session — the trace panel's near-miss gating and the settings screen's new section are verified at the unit level (`nearMiss()`'s five cases) and by reading the wiring, not by an interactive click-through; re-verify visually once a real abstention with a near-miss exists in a cold-started browser session.

### Added

- `askwell.retrieve` — `get_retrieval_threshold`, `set_retrieval_threshold`, `InvalidThreshold`, `register_retrieval_threshold` (`GET`/`POST /settings/retrieval-threshold`).
- `web/lib/retrieval-threshold.ts` — `fetchRetrievalThreshold`, `setRetrievalThreshold`, `nearMiss`, `recordThresholdChanged`/`getThresholdChangesCount`.
- `web/components/settings/retrieval-threshold.tsx` — `RetrievalThresholdControl`, shared by the trace panel and the settings screen.

### Changed

- `web/components/ask/trace-panel.tsx` — offers `RetrievalThresholdControl` below the step list when `nearMiss()` finds one.
- `web/app/settings/page.tsx` — new "Retrieval threshold" section.

## 0.4.38 - 2026-09-20

`M5-TRACE-FE-121` — trace interactions: expand, click through, copy. The last ticket in the `TRACE` chain (`M5-TRACE-FE-119`/`-120`/`-BE-125`).

A retrieved passage that the answer actually cited now shows its full text and a click-through to the source viewer at that position, reusing `documentHref`/`useDeletion`/`pageLabel` from the answer's own citation cards rather than a second read path — `web/lib/trace.ts`'s new `hitCitation` matches a trace hit's `chunk_id` against the turn's own `citations` (both sides stringify the same `candidate.chunk_id`, confirmed in `askwell.ask`). A hit the answer never actually cited (a near-miss, or one outscored for its claim) still renders only its score, since nothing else was ever sent to the browser for it. A passage from a since-deleted document renders greyed and not clickable, exactly like the answer's own cards. A memory fact in the trace is now the same `MemoryChip` an answer's claim renders — "the same popover... with correct and delete" is only true reusing that component, so it moved out of `ask-screen.tsx` into its own `web/components/ask/memory-chip.tsx` (avoiding a circular import back from `trace-panel.tsx`). "Copy trace" (`web/lib/trace.ts`'s new `buildTraceCopyText`) produces plain text with the question, backend, every step's summary/duration/scores/threshold/query, the tool-ceiling note, and a stated truncation past 20,000 characters.

The trace panel's open/closed state moved from a local `useState` to `AskProvider` (`ask-state.tsx`'s new `openTraceTurnId`/`openTrace`/`closeTrace`) — clicking a passage navigates away to the source viewer, which unmounts the panel's own page, and only state held above the router survives that round trip. Returning via the viewer's existing "Back to answer" link (`ContextRail`) lands back on `/` with the same turn's trace panel still open, satisfying the ticket's own assumption without any new query-param plumbing.

**Verified**: `scripts/dev.sh web-check` clean (lint, typecheck, 285 tests including 6 new ones for `hitCitation`/`buildTraceCopyText`, production build, token hygiene, contrast, offline check). Confirmed by reading `askwell.ask` that a `citation` event's `chunk_id` and a `retrieve` trace step's `hits[].chunk_id` are both `str(candidate.chunk_id)` of the same value, so the join `hitCitation` relies on is sound. **No browser available in this session, and the development database currently has no ingested documents or citations to click through** — the interactive round trip (click a passage, land in the viewer, return to a still-open trace; click a fact, correct it) was not exercised end-to-end against a real corpus. Re-verify visually once a corpus exists, or in the cold-start walkthrough this ticket's own Testing Notes describe.

### Added

- `web/lib/trace.ts` — `hitCitation`, `buildTraceCopyText`, `recordTraceCopy`/`getTraceCopiesCount`.
- `web/components/ask/memory-chip.tsx` — `MemoryChip`, split out of `ask-screen.tsx` for reuse by the trace panel.
- `web/components/ask/ask-state.tsx` — `AskApi.openTraceTurnId`/`openTrace`/`closeTrace`.

### Changed

- `web/components/ask/trace-panel.tsx` — `RetrieveStepDetail` renders a clickable, full-text passage for any cited hit; `MemoryRetrieveStepDetail` renders `MemoryChip` instead of static text; the panel header gained a "Copy trace" button.
- `web/components/ask/provenance-margin.tsx` — `useDeletion` exported for reuse.

## 0.4.37 - 2026-09-20

`M5-TRACE-FE-120` — what is inside a trace step's raw detail, formatted per `docs/ux/trace.md` §3 rather than the raw JSON `M5-TRACE-FE-119` left as every step's expander. A `retrieve` step now shows every candidate's score against the threshold, sorted highest first, so the near-miss that explains an abstention ("the right passage at 0.61 under a 0.65 threshold") reads as the top of the list rather than something to hunt for in JSON. A `memory_retrieve` step's ids are resolved to the fact's own subject, value and origin marker (`GET /memory/facts/{kind}/{id}`, the same read a chip's popover already uses) rather than left as bare UUIDs. A database turn — whether the single-shot `sql` path or a `database_query` tool call inside the loop — shows its query (`QueryDisclosure`, reused from `sql-result-table.tsx`, whose existing `LIMIT ... /* Added by Askwell */` highlighting is what surfaces the injected limit without a second field), its outcome, and, when rejected or failed, the full reason — never truncated, since it is the diagnostic `../audit-log.md` §7 exists to keep visible. A flagged tool call's C7 injection patterns render as plain metadata, no warning colour. Backend and model are now named once per turn, above the step list, from `trace.backend`; a tool-ceiling stop shows "Stopped after 8 steps for this question." and what it was about to do (`trace.loop_pending_calls`), below the step list.

Issue #428 (`trace-panel.tsx`'s memory-fact origin marker checked `origin === "user"`, a value no memory fact's own origin — `clarification`/`correction`/`manual`/`inferred` — ever is, so a supplied fact always rendered hollow) does not apply to this change: `MemoryRetrieveStepDetail`, built fresh for this ticket, uses `origin !== "inferred"` from the start, the same check `ask-screen.tsx` and `memory-screen.tsx` already use.

No browser available in this session. Verified against the real running stack instead: a synthetic rich trace (every step kind this ticket covers, plus three real `schema_notes`/`memory` rows spanning `user`/`correction`/`inferred` origin) written directly to a message's `trace` column, then read back through the cookie-authenticated `GET /ask/{message_id}/trace` and `GET /memory/facts/{kind}/{id}` exactly as the panel's own fetch calls would — confirming the wire shapes this ticket's rendering code assumes match what the running API actually returns, for all three origin cases including the one #428 named. Synthetic data removed afterward.

### Added

- `web/lib/trace.ts` — `retrievedHits`, `retrievalThreshold`, `memoryFactRefs`, `sqlStepInfo`, `toolInjectionPatterns`, `toolCeilingPendingCalls`, and the `TraceBackend`/`PendingToolCall` wire types.
- `web/components/ask/trace-panel.tsx` — `StepDetail` dispatch plus `RetrieveStepDetail`, `MemoryRetrieveStepDetail`, `SqlStepDetail`, `ToolStepDetail`, `BackendLine`, `ToolCeilingNote`.

## 0.4.36 - 2026-09-20

`M5-TRACE-FE-119` — the trace panel: "How did you get this?" A toggle under any answer (streaming, completed, abstained, stopped or failed) opens a panel over Ask — never a page, so the reader never loses their place in the conversation — showing `GET /ask/{message_id}/trace`'s stored steps as a numbered vertical sequence: a plain-language summary line and a duration per step, raw detail (the step's own JSON, verbatim, per C4) expandable underneath rather than in a separate mode. Timings are always visible, never behind the expander. A step whose only fields are `kind` plus whatever the summary and duration already surfaced gets no expander at all — the stated edge case for "nothing worth expanding." Opened while a turn is still running, the panel polls the same endpoint every second and stops the moment the fetched trace itself is no longer `"running"`; a rotated trace (`docs/architecture.md` §7.1's ring buffer) shows the stated "cleared" copy instead of an empty step list, which would otherwise look identical. A local, untransmitted counter (C1) records opens, matching `lib/ask.ts`'s existing `inlineClarificationsShownCount` shape.

`web/lib/trace.ts`'s `stepSummary` reads the raw, differently-shaped-per-`kind` object `askwell.ask` actually persists (`retrieve`, `abstain`, `memory_retrieve`, `inline_clarification`, `compose`, `schema`, `sql` with its several `outcome` values, and `tool`/loop steps named by their real tool) rather than a friendlier shape invented for this ticket — verified against a real, completed trace read back through the running stack (`GET /ask/{id}/trace`, cookie-authenticated), not just fabricated fixtures. Formatting *within* a step's raw detail (rendering scores against the threshold, a clickable passage, a copyable query) is `M5-TRACE-FE-120`'s own scope and deliberately not attempted here; an unfamiliar step kind falls back to naming itself literally rather than a blank line, so a future step type is never silently dropped from the sequence.

Issue #425 (a tool-loop turn's mid-turn trace poll returns no steps until the loop finishes) is confirmed live now that a real client polls mid-turn, and re-owned rather than fixed — the fix is backend-only (`run_tool_loop`'s existing `ToolCallObserver` appending to `trace_steps` incrementally) and out of this ticket's own scope, which is the panel over whatever the endpoint returns. No browser available in this session, so the panel was not visually screenshotted — the summary/duration/expander logic was verified directly against a real trace payload read from the running stack instead.

### Added

- `web/lib/trace.ts` — `fetchTrace`, `stepSummary`, `formatDuration`, `hasExpandableDetail`, `traceRows`, `recordTraceOpened`/`getTraceOpensCount`.
- `web/components/ask/trace-panel.tsx` — `TraceToggle`/`TracePanel`, wired under both the live and collapsed-turn answer views in `ask-screen.tsx`.

## 0.4.35 - 2026-09-20

`M5-TRACE-BE-125` — `GET /ask/{message_id}/trace` serves `messages.trace` to the browser for the first time; nothing did before this, which is why `M5-TRACE-FE-119` (issue #415) was blocked. Returns the stored trace verbatim (C4: never recomputed) — the step sequence plus `trace_rotated`/`steps_truncated`. An unknown `message_id` is a 404; a message that exists with `trace IS NULL` (a turn that failed before `_run_generation` ever wrote one) is a valid empty-step trace instead. A turn still `running` is served from the new `_Turn.trace_steps` — the same list `_run_generation` builds `messages.trace` from, shared by reference so a step is visible the moment it is appended, before the row that will eventually hold it is written at all.

### Added

- `GET /ask/{message_id}/trace` (`api/src/askwell/ask.py`).
- `_Turn.trace_steps` — a running turn's steps, readable before the final database write.

`M5-LOOP-FE-118` — a live tool call's `step` events now carry `call_id` and `phase`, and `askwell.ask._emit_tool_call_step` forwards both `"start"` and `"end"` instead of only `"end"` (the `M5-LOOP-BE-117a` stopgap issue #420 named, closed here). `_tool_call_step` names each phase for its real operation — "Searching your files." / "Searched your files.", "Querying your database." / "Queried your database.", and so on per tool — rather than the raw `"Called {tool}."` placeholder, and a failed call's `"end"` says so ("That didn't work — trying another way.") instead of freezing on the label its `"start"` used. `web/lib/ask.ts::applyAskEvent` keys a step on `call_id` when present: an `"end"` updates its own `"start"`'s entry in place rather than appending a second line for the same call, and two calls dispatched in the same batch keep separate entries the whole time — which is what renders them concurrently rather than as a queue, since both are visible at once. A generic step with no `call_id` (retrieval, SQL) is unaffected and still always appends.

Source-scoped wording (the backlog ticket's own `"querying sales-2024"` example) is deferred to issue #422 — `ToolCallEvent.arguments` carries only a `source_id` UUID, and resolving it to a name needs a database read the observer's synchronous signature cannot make without a scope change `M5-LOOP-BE-117a` deliberately left out.

### Added

- `AskStepData.call_id` / `.phase` (`web/lib/ask.ts`), `AskTurnState.steps[].callId`.
- `askwell.ask._tool_call_step`, tested directly in `api/tests/test_ask_tool_step_labels.py`.

### Changed

- `askwell.ask._emit_tool_call_step` forwards both tool-call phases instead of only `"end"`.
- `applyAskEvent`'s `"step"` case updates a step in place when `call_id` matches an existing entry, instead of always appending.

## 0.4.33 - 2026-09-20

`M5-LOOP-BE-117a` — `run_tool_loop` (`api/src/askwell/agent/loop.py`) takes an optional `on_tool_call` observer that fires once per call actually dispatched: a `"start"` event immediately before it runs, an `"end"` event immediately after, including inside a concurrent `asyncio.gather` batch, where every `"start"` in the batch fires before any of that batch's `"end"`s — proven in `api/tests/test_loop.py` with two staggered fake tools that finish in the opposite order they were dispatched. A deduplicated call, never actually run, fires no event; a failed call still fires its `"end"`, marked with the real outcome. An observer that raises is swallowed and logged (`_notify`), same posture as `askwell.traces.TraceRing.write` — a caller's own bug in a callback watching the turn is not a reason to fail it. With no observer given, `run_tool_loop`'s behaviour is unchanged.

`askwell.ask`'s two `run_tool_loop` call sites now emit their `"Called {tool}."` step live from this observer instead of bursting one per tool after the whole loop finished — the label lands when that call actually returns. Only the `"end"` phase reaches `turn.emit` for now (issue #420): the shipped frontend has no phase/call-id discriminator yet to collapse a `"start"`/`"end"` pair into one visible label, so surfacing both today would double every step the Ask screen renders. `M5-LOOP-FE-118` owns that discriminator and switches this to both phases once it lands. The pre-loop generic label ("Working through this in steps." / "Continuing where it left off.") is kept as the only signal until a call actually finishes, rather than dropped outright — removing it would have reopened the "working for twenty seconds looks hung" problem for a turn's first call, which is this ticket's whole reason to exist.

### Added

- `askwell.agent.loop.ToolCallEvent` / `ToolCallObserver`, and `run_tool_loop(..., on_tool_call=...)`.

### Changed

- `askwell.ask`'s loop call sites emit `step` events live per call instead of in a post-loop burst.

## 0.4.32 - 2026-09-20

`M5-EVAL-TEST-124` — the quality gate's "Tool selection incl. parallel" category (`docs/build-plan.md`'s 25-task, ≥0.85 row) gets its suite. `eval/tool_selection.py` drives the real `askwell.agent.loop.run_tool_loop` — not a mock of it — over both the fixture document corpus and the fixture sandbox database seeded together, so a task can genuinely need either, both, or neither. Every task is scored on two things kept separate rather than folded into one number: `tool_choice_score` checks the distinct tools the loop actually called against a task's `expected_tool_routes` (more than one accepted route is scored correct — the "two acceptable tool routes" edge case; an empty route covers "the correct behaviour is no tool at all"), and the ordinary `eval.scoring.score` grades the final answer text — so a right answer reached by the wrong tool, or a wrong answer despite the right tool, is visible rather than averaged away.

Parallel dispatch gets its own check rather than being assumed from a passing answer: `parallel_achieved` looks at `LoopStep.iteration` for two freshly-dispatched (non-deduplicated) calls sharing one iteration — the one trace signature `asyncio.gather`-based dispatch produces and a regression to one-call-per-iteration cannot fake. A task marking `require_parallel` scores its tool component 0 if that signature is absent, independent of whether the right tools were eventually called — proven by `eval/tests/test_tool_selection.py`'s own "parallel required but not achieved scores zero" case, so removing parallel dispatch from the loop fails exactly the tasks built to catch it. Recovering from a real tool error (asking the connected database about a table that does not exist) is graded with a new `not_contains_any` scorer — the failure this exists to catch is a fabricated number standing in for an honest "I don't have that," not a fluent-sounding wrong answer. The suite is wired into `eval/bench.py` (`--suite tool_selection.v1`) and `.github/workflows/eval.yml`'s gate loop.

### Added

- `eval/tool_selection.py` — `run_tool_selection_suite`, `tool_choice_score`, `parallel_achieved`, `combined_tool_score`.
- `eval/suites/tool_selection.v1.json` — 25 tasks.
- `eval.scoring._not_contains_any` (`"not_contains_any"` scorer).
- `eval.suite.Task.expected_tool_routes` / `.require_parallel`, and the `"tool_selection"` suite mode.

## 0.4.31 - 2026-09-20

`M5-LOOP-BE-117` — the two gaps left in `messages.trace` (`docs/architecture.md` §7.1) after every earlier trace-populating ticket: a missing step kind, and a store that never actually rotated. A database turn's schema lookup (`askwell.agent.sql_generate.generate_candidate_query`) now times itself and reports its own `"schema"` step — `kind`, `ms`, `source_id` — carried on `_SqlAnswer.schema_step` and prepended ahead of the `"sql"` step in every branch that got as far as selecting a source, matching the doc's own worked example ("Looked up schema" before "Queried sales-2024") rather than folding that time into the SQL step's. The executed-query step also gained `limit_injected`, the one field `docs/architecture.md`'s shape names that nothing populated yet.

Second: `messages.trace` had never actually rotated with the file-backed `TraceRing` it is documented to rotate with — the DB column kept every turn's full step detail forever regardless of what aged out on disk. `TraceRing.prune()` now reports the message ids it actually dropped (`TraceRing.write()` returns a `TraceWriteResult` carrying them), and `askwell.ask._trim_rotated_traces` clears `steps` for exactly those rows — in the same transaction as the triggering turn's own write — leaving every other trace field (`status`, `backend`, …) intact so a reopened old turn still renders, and leaving citations and fact usage untouched entirely, since those are real tables and never rotate. A `"steps_truncated"` flag was also added, covering the ticket's own named edge case — a turn whose own trace exceeds a new 50-step per-turn bound (`TRACE_STEP_BOUND`) is truncated with that fact stated on the trace itself rather than silently cut.

### Added

- `askwell.agent.sql_generate.GeneratedQuery.schema_lookup_ms` and the `"schema"` trace step it feeds.
- `TraceWriteResult` (`askwell.traces`) — `TraceRing.write()`'s new return shape, carrying which message ids rotated out.
- `askwell.ask._trim_rotated_traces` — trims `messages.trace.steps` for a rotated-out trace.
- `askwell.ask.TRACE_STEP_BOUND` / `_bound_trace_steps` — the per-turn trace size bound and its `steps_truncated` flag.

## 0.4.30 - 2026-09-20

`M5-LOOP-BE-116` — the 8-call ceiling `M5-LOOP-BE-115` deliberately left as a crash guard becomes the product's real, user-visible one. `askwell.agent.loop.CALL_CEILING` (8, `docs/architecture.md` §10) is now enforced inside `run_tool_loop` itself: a parallel batch that would cross it is truncated at 8, and the calls that were cut are never dispatched — they surface on the new `LoopResult.pending_calls` instead, the trace's own "what it was about to do" (`docs/ux/trace.md` §5). A ceiling reached one call at a time (no single batch ever crosses it) is caught at the next iteration by a dedicated `_stop_at_ceiling` helper, which asks the model exactly one more time — told plainly that no further tool calls will run — to compose from what is already gathered; if it asks for tools anyway, that request becomes `pending_calls` instead of being honoured. Composing from nothing is refused outright: if none of the 8 calls actually succeeded, the turn says so (`_NOTHING_GATHERED_TEXT`) rather than asking the model to invent something, the ticket's own named edge case. A stopped-early answer's note (`_CEILING_NOTE`) is appended by the loop itself, never left to the model to remember, so the Validation Rule ("never omit the note") holds regardless of what the model wrote.

**Continue is a new turn, not a resumed one.** `LoopResult.continuation` (a `LoopContinuation` of just the `<tool-result>` history and the next citation index) is produced only on a turn's first ceiling stop, persisted verbatim into `messages.trace.loop_continuation` by `askwell.ask`, and read back by a new `POST /ask` field, `continue_from`, naming the turn to pick up from. `_run_generation` resolves it before deciding anything else: found, the turn skips `_run_sql_turn` and `_has_hybrid_sources` entirely and calls `run_tool_loop(resume=...)` directly, with its own fresh 8-call budget — the point of a new turn is a new budget, not a shared one — seeded with the earlier turn's gathered results so the model has no reason to re-fetch them. Not found (a stale, wrong, or non-loop id), the turn answers as an ordinary new question instead of failing. Cross-turn tool-call dedup is deliberately not attempted (`LoopContinuation`'s own docstring): seeding the history already gives the model what it needs without asking again, and reconstructing the dedup cache would mean persisting each tool's raw content a second time for no real benefit. A second ceiling stop in the same chain (`continuation_count >= 1`) narrows the answer's text instead of offering a third continuation, so there is no infinite chain — the ticket's own named edge case.

The `done` SSE event gained `tool_ceiling`/`can_continue` so the browser can render `docs/ux/ask.md` §5's "Tool ceiling hit" state and post `continue_from` back as the stopped turn's own `message_id`. `/ask/counts` gained `tool_ceiling_stops`, the ticket's own local counter (C1: read from this machine's rows on demand, transmitted nowhere), and the `ASK_ASKED` interaction-log record gained a `tool_ceiling` field — its own Audit / Logging Requirement, distinct from the trace ring buffer, which rotates.

### Added

- `askwell.agent.loop.CALL_CEILING`, `LoopContinuation`, `_stop_at_ceiling`.
- `LoopResult.pending_calls`, `.continuation`, `.continuation_count`; `"tool_ceiling"` as a `stopped_reason`.
- `AskRequest.continue_from`; `askwell.ask._load_loop_continuation`, `_LoopContinuationState`.
- `messages.trace` fields `loop_pending_calls`, `loop_continuation`, `loop_continuation_count`.
- `/ask/counts` → `tool_ceiling_stops`; `done` event → `tool_ceiling`, `can_continue`.

**Verified**: `scripts/dev.sh lint`/`format`/`typecheck` clean; `scripts/dev.sh test` (13 new cases in `test_loop.py` covering a truncated batch, a one-at-a-time ceiling, nothing gathered, a `Continue` resume with a fresh budget, and a second stop narrowing rather than offering a third continuation — 832 passed, 1 skipped, no regressions); `scripts/dev.sh test-db` against the real, already-running stack (all `test_ask_*` cases pass, including one existing counts test updated for the new `tool_ceiling_stops` field; full `test-db` run confirmed clean). A live cold-start round-trip hitting the ceiling against a running local model was not exercised — the inference bridge was not serving a model in this environment, the same gap `M5-LOOP-BE-115` and several tickets before it hit for the identical reason (#376).

## 0.4.29 - 2026-09-20

`M5-LOOP-BE-115` — the multi-step tool loop, wired into `POST /ask`. New `askwell.agent.loop.run_tool_loop` gives the model the registry `M5-TOOLS-BE-113`/`-114` built: it asks the model for one JSON decision at a time (`{"type": "tool_calls", "calls": [...]}` or `{"type": "answer", "text": "..."}`), calls every tool the model names in one turn concurrently via `asyncio.gather` — none of the five tools write anything, so independent lookups never wait on each other — feeds every result back as a `<tool-result>` block, and asks again until the model says it has enough. A repeated call (same tool, same arguments, this iteration or an earlier one) is never re-executed; its prior result is reused and the step is recorded `deduplicated=True`. A tool error is told to the model as data, not raised, so the turn can try a different approach — the ticket's own edge case, now covered by `test_a_tool_error_mid_loop_is_told_to_the_model_and_the_turn_recovers`. `_SAFETY_MAX_ITERATIONS` (25) is a crash guard only, well above the 8-step ceiling `M5-LOOP-BE-116` will actually enforce and surface to the user.

**`askwell.ask._run_generation` only tries the loop for a genuinely hybrid corpus** — `_has_hybrid_sources` requires at least one `ready` document and one `ready` database-backed source, checked before the loop is attempted at all, and never for a source-scoped question. An ordinary single-kind corpus (the overwhelming majority of existing turns, and every turn `test_ask_api.py`/`test_ask_sql.py` already exercise) falls through unchanged to `_run_sql_turn` and the single-shot document path exactly as before this ticket, with memory, partial-coverage, conflict detection and citations all intact. This is a deliberate narrowing of scope versus wiring the loop in unconditionally (issue #409's own finding, from an audit of this ticket) — the near-term fix that issue itself recommends, chosen because the alternative would have silently dropped those shipped features from ordinary traffic. Two related gaps are tracked, not fixed here: a loop-answered turn's `[index]` markers do not yet resolve into the `citations` table or a `citation` SSE event (issue #407, its own follow-up ticket), and `_run_sql_turn` is still tried first on every turn, so a hybrid question whose database half alone matches a schema note strongly enough can still short-circuit before the loop runs (issue #408, left as documented risk pending #407).

### Added

- `askwell.agent.loop` — `run_tool_loop`, `LoopStep`, `LoopResult`.
- `tool_loop.v1.md` — the loop's system prompt: tool results as C7 data, the two-shape JSON protocol, citation-by-index.
- `askwell.ask._has_hybrid_sources` — the gate deciding whether a turn is even offered to the loop.

**Verified**: `scripts/dev.sh check` (lint/format/typecheck clean); `scripts/dev.sh test` (827 passed, 1 skipped, unchanged from before this ticket — the loop is pure Python with no I/O of its own, covered entirely without a database); `scripts/dev.sh test-db` (630 passed against the real, already-running stack — 624 before this ticket plus 6 new `_has_hybrid_sources` tests against real `sources`/`documents` rows; zero regressions in `test_ask_api.py`/`test_ask_sql.py`, confirmed by inspection that neither fixture ever creates a database-backed source alongside a document one, so the new gate never fires there). A live cold-start `POST /ask` round-trip through a running local model was not possible in this environment — the inference bridge container was not actually serving a model at the time of this change — so the model-interaction protocol is verified by `test_loop.py`'s fakes and the wiring by `test_ask_hybrid_sources_db.py`'s real rows, not by a live generation.

## 0.4.28 - 2026-09-19

`M5-TOOLS-BE-114` — C7 extended from retrieved document passages to tool results: a database row, a schema note, a filename returned by any of the five tools `M5-TOOLS-BE-113` registered is exactly as untrusted as retrieved text, and now gets the identical treatment. `askwell.agent.compose.delimit_tool_result` wraps a tool call's result in its own `<tool-result index="…" tool="…">` block, labelled by origin, with a new `_escape_forged_delimiter` neutralising any literal `<tool-result`/`</tool-result>` found inside the data first — unlike `delimit_candidates`, which does not escape a candidate's own content, a tool result can carry text an attacker fully controls (a row in an imported dump, C3), so the boundary here is unforgeable rather than merely delimited. The prompt file's standing C7 statement (`answer_composition.v1.md`) now names `<tool-result>` explicitly alongside `<retrieved-content>`, with its own worked example. `askwell.agent.tools.ToolStep` gained `injection_flagged`/`injection_patterns`, computed unconditionally inside `_step` by flattening a result's content to its string leaves and reusing `askwell.agent.compose.flag_injection_text` — the same heuristic a retrieved passage already goes through, not a second copy of it — so every tool call is flagged on the trace the moment it runs, without waiting for the loop that will actually call tools more than once per turn (`M5-LOOP-BE-115`, still not built). Flagging never blocks: a flagged result is returned and answered exactly like an unflagged one, per this ticket's own out-of-scope line.

### Added

- `askwell.agent.compose.TOOL_RESULT_TAG`, `delimit_tool_result`, `_escape_forged_delimiter`.
- `askwell.agent.tools.ToolStep.injection_flagged`/`injection_patterns`, computed in `_step` via a new `_flatten_strings`.
- `answer_composition.v1.md` — "Tool results" section and the standing statement's explicit coverage of `<tool-result>` blocks.

### Changed

- `docs/architecture.md` §9, `docs/ux/trace.md` §3, `docs/states-and-edge-cases.md` §2 — prompt-injection defence and the trace/state rows now name tool results, not only retrieved content.

**Verified**: `scripts/dev.sh check` (819 passed, 1 skipped, lint/format/typecheck clean) — including new tests asserting the C7 standing statement and `<tool-result>` delimiter survive in the prompt file (fail if either is edited out, mirroring the existing `<retrieved-content>` tests), that a delimiter forged from inside tool-result data cannot close the block early, that an instruction-like tool result is flagged but still answered normally, that a legitimately instructional tool result (a policy row) is flagged and not blocked, and that flags are computed independently per step across a chain of several tool calls.

## 0.4.27 - 2026-09-19

`M5-TOOLS-BE-113` — the tool registry, M5's first ticket and the SQL epic's own five checked stages (generation, C2 validation, limit injection, dry run, execution) given a second caller shape: a bounded, structured-error `ToolResult` rather than a `messages.trace` step and an SSE event. New `askwell.agent.tools` exposes exactly five tools — `document_search` (wraps `retrieve()`), `database_query` (re-runs `askwell.agent.sql_generate` → `askwell.sql.validate` → `askwell.sql.limit` → `askwell.sql.dry_run` → `askwell.sql.execute`, the same chain `askwell.ask._run_sql_turn` already assembles for the single-shot turn), `schema_lookup` (`askwell.memory.get_active_schema_notes`), `document_listing` and `current_date` — through one registry, `TOOLS`, so a sixth tool is a decision made here rather than an accretion. `call_tool` validates arguments with a `pydantic` model per tool (`extra="forbid"`), times the call, and turns every failure — an unknown tool name, invalid arguments, a rejected query, no connection, or the handler itself raising — into a `ToolResult`/`ToolStep` pair rather than an exception, so the loop that will call these (`M5-LOOP-BE-115`, not built yet) never needs its own `try`/`except`. Each tool bounds its own result and states the truncation on the result itself (top 8 passages, 50 schema notes, 50 listed documents, 50 displayed rows) rather than silently clipping. **Not wired into `POST /ask`** — the loop that would call this registry more than once per turn is the next ticket's job, the same "do not wire ahead of the caller that does not exist yet" posture `M4-SQL-DB-107` and `M4-SQL-BE-103` both took about themselves.

### Added

- `askwell.agent.tools` — `TOOLS`, `Tool`, `ToolResult`, `ToolError`, `ToolErrorCode`, `ToolStep`, `call_tool`, and the five handlers.

**Verified**: `scripts/dev.sh check` (808 passed, 1 skipped, lint/format/typecheck clean); `scripts/dev.sh test-db` (624 passed against the real, rebuilt stack, including 7 new tests exercising `schema_lookup`/`document_listing`/`database_query` against real rows); a real cold-start run inside the rebuilt `api` container — `current_date` returned with no database or model touched, `document_listing`/`schema_lookup` read real rows, an unknown tool name and an invalid `source_id` both came back as structured errors, and passing no real inference client to `database_query` was caught by `call_tool`'s own exception containment and returned as a `failed` outcome rather than crashing.

## 0.4.26 - 2026-09-19

`M4-RESULT-FE-111` — the last of the `SQL` epic's five database states: no connections configured, unreachable, zero rows, timeout, rejected. Four already had distinct messages (`unreachable`/`timeout`/`rejected` from `askwell.sql_execute`/`askwell.sql.validate`, `zero_rows` from `M4-RESULT-FE-109`); the fifth — a database-shaped question with nothing connected at all — did not exist until this ticket. New `askwell.ask._no_database_answer` fires only from the document turn's own abstention branch, after document retrieval has already found nothing (issue #400's own recommended fix): a database-shaped question is answered from the user's documents whenever they actually cover it, and is only ever reported as unconnected once that has genuinely failed, closing #400's short-circuit concern by construction rather than by tuning a word list. `_looks_database_shaped` is deliberately narrow (`"database"`/`"sql"` only) — a wider list matches ordinary business prose and the abstention eval's own near-miss questions, which must never be misdiagnosed as a missing connection. Two named edge cases from the same helper: a relevant source that is still importing says so rather than "unreachable", and several connections where one needs attention names which. `db_state` is a new field on the `done` event and `AskTurn`, read by `AbstentionState`'s one add-source control (`web/lib/ask.ts`'s `addSourceActionLabel`) to relabel it "Connect a database" for the no-connections case and drop it entirely for the other two, since adding a new source fixes neither.

### Added

- `askwell.ask._looks_database_shaped`, `_non_ready_sql_sources`, `_no_database_answer` — the "no connections configured" state and its two edge cases.
- `db_state` on the `done` event, `AskDoneData`, and `AskTurn` (`web/components/ask/ask-state.tsx`).
- `addSourceActionLabel` (`web/lib/ask.ts`) — the pure decision behind `AbstentionState`'s one control.
- `docs/states-and-edge-cases.md` §4 — the "no connections configured" row's real copy, plus the two new "still importing"/"needs attention" rows.

### Changed

- `web/components/settings/connections.tsx` — the empty state now says what connecting enables and that credentials must be read-only (`states-and-edge-cases.md` §7).

## 0.4.25 - 2026-09-19

`M4-RESULT-FE-110` — the generated query is disclosed for every database answer, not only the ones that executed. `QueryDisclosure` (`web/components/ask/sql-result-table.tsx`) is now the one collapsed-by-default control both an executed result (`SqlResultTable`) and every other outcome (`SqlQueryCard`, new) render, so a database answer looks like one system whether or not the query ran. Expanding it marks the injected `LIMIT` clause distinctly from the rest of the query (`segmentInjectedLimit`, matching the trailing `/* Added by Askwell */` comment `askwell.sql.limit` already attaches), scrolls rather than wraps or truncates a very long query, and adds a **Copy query** action. Disclosure on a rejection, a failed dry run, a timeout, a query-time failure or the source vanishing mid-turn needed a new wire field — `sql_result` deliberately stays `None` on every one of those branches (C2's own "never executed" contract) — so `askwell.ask` now also sends `sql_query` (`{query, outcome}`) on the `done` event for exactly the branches `sql_result` does not cover, reconstructed from the already-stored `messages.trace` on a reopened turn rather than a second stored column.

### Added

- `askwell.ask._sql_query_disclosure`/`_sql_query_from_trace`, `AskDoneData.sql_query` — the disclosure `sql_result` never carries.
- `web/lib/sql-result.ts` — `SqlQueryDisclosure`, `segmentInjectedLimit`, the local disclosures-expanded counter (C1: never transmitted).
- `SqlQueryCard` (`web/components/ask/sql-result-table.tsx`) — the disclosure-only card for a database answer with no `sql_result`.
- `AskTurn.sqlQuery` (`web/components/ask/ask-state.tsx`).

### Changed

- `QueryDisclosure` (`web/components/ask/sql-result-table.tsx`) — exported, adds the injected-limit marking, scrolling instead of wrapping, and **Copy query**.

## 0.4.24 - 2026-09-19

`M4-RESULT-FE-109` — a database-answered turn renders as a table, not just a sentence, now that `M4-SQL-BE-108a` gives it a real `sql_result` to render from. `SqlResultTable` (`web/components/ask/sql-result-table.tsx`) covers the ticket's own four states: a single value shown as a number rather than a one-cell table, a zero-row result labelled distinctly from an error or an abstention, an ordinary result as a client-paginated table with type-inferred column alignment and null/empty cells rendered distinguishably, and a truncated result labelled "first N of possibly more" whenever the injected `LIMIT` was actually hit. The query is disclosed unconditionally behind a "Show query" toggle, matching `states-and-edge-cases.md` §4's "the query is the citation". "View full result and query" opens the database row of the source viewer (`/documents/?result=<message_id>`, `database-result-view.tsx`) — reading the live turn out of `AskProvider` first, exactly as the document viewer's own `ContextRail` does, and falling back to replaying `GET /ask/{message_id}/stream` only if a reload dropped that in-memory state, so a paged-through result is never re-queried. Closes issues #375 and #386.

### Added

- `web/lib/sql-result.ts` — `SqlResultData` and the pure pagination/formatting/alignment helpers behind the table.
- `web/components/ask/sql-result-table.tsx` — the table itself, wired into `AnsweredContent` (`ask-screen.tsx`) for both the live and a collapsed-and-reopened turn.
- `web/components/documents/database-result-view.tsx` — the source viewer's database row.
- `AskDoneData.sql_result` (`web/lib/ask.ts`), `AskTurn.sqlResult` (`web/components/ask/ask-state.tsx`).

## 0.4.23 - 2026-09-19

`M4-SQL-BE-108a` — the checked query path finally runs, and its rows survive a reopen. `askwell.ask._run_sql_turn` wires `askwell.agent.sql_generate` → `askwell.sql.validate` → `askwell.sql.limit` → `askwell.sql.dry_run` → the new `askwell.sql.execute` into every turn, ahead of document retrieval — a question with no relevant connected database falls through to the document path exactly as before. The new module wraps `askwell.sql_execute` (`M4-SQL-DB-107`) rather than duplicating it, adding truncation labelling and its own `sql_execute` audit kind. `messages.sql_result` (migration `7f40fa52d49d`) stores columns, rows, row count, truncation and duration as a snapshot at answer time, carried on every `done` event — live or replayed after a reopen — and reset to `NULL` if the write that would have persisted it rolls back, so the live stream never shows rows the database does not actually hold (closes issue #390). Fixes the stale "not wired into `POST /ask`" claims left in `askwell.agent.sql_generate`'s own module docstring and in the `M4-SQL-VAL-106` decision-log entry (issue #392), and closes issue #375.

### Added

- `askwell.sql.execute.execute_checked_sandbox_query`/`execute_checked_connection_query`/`ExecuteResult`.
- `messages.sql_result` (`jsonb`, nullable).
- `askwell.ask._run_sql_turn`/`_SqlAnswer` — the checked path's turn-flow wiring.

### Fixed

- `askwell.agent.sql_generate`'s own module docstring, and the `M4-SQL-VAL-106` decision-log entry, no longer claim the SQL path is unreachable from `POST /ask` (#392).
- A rolled-back audit write can no longer ship a live `sql_result` the persisted message does not hold (#390).

## 0.4.22 - 2026-09-19

`M4-DUMP-SEC-091` — the containment claim demonstrated, not just asserted. `api/tests/test_dump_containment.py` runs six hostile fixture dumps (privilege escalation, reading a host file through `COPY ... FROM PROGRAM`, connecting to another database in the sandbox instance, reaching the network, exhausting disk, running indefinitely) through the real `import_dump` against a real sandbox instance. Every fixture must fail loudly, land the source in `attention` with a reason, record `dump_import_failed`, and drop the sandbox database — checked against a content hash (not a row count) of Askwell's own database and of a second, already-loaded sandbox database, both before the suite and after every single fixture, plus a whole-suite-in-sequence run confirming the product stays functional afterwards. Also resolves issue #389: `test_sandbox_network_has_no_route_to_the_proxy_or_the_internet` is a static assertion, parsed straight out of `compose.yaml`, that the `sandbox` network is `internal: true` and joined by nothing but `api`, `worker` and `sandbox` itself — the topology regression that would make the proxy's refusal counter matter, catchable in CI without a running proxy or Redis. The counter check itself stays the ticket's own cold-start manual walkthrough, now written up in `docs/manual-tests/M4-DUMP-SEC-091.md` and run against the real stack.

### Added

- `api/tests/test_dump_containment.py` — the hostile-dump containment suite, `requires_db`, plus an unmarked topology assertion.

## 0.4.21 - 2026-09-19

`M4-SQL-VAL-106` — an `EXPLAIN`/`SHOWPLAN` dry run before a validated, limited query ever executes. `askwell.sql.dry_run.dry_run_sandbox_query`/`dry_run_connection_query` plan a query, under the same read-only role and statement timeout execution uses, without running it: Postgres and MySQL/MariaDB via `EXPLAIN`, SQL Server via a session-level `SET SHOWPLAN_ALL ON`. A query whose planner rejects it (a dropped column, a renamed table) comes back `DryRunReason.PLANNING_FAILED` and is recorded to `audit_interactions` as `sql_dry_run` — a different kind from `validate.SQL_QUERY`, so a planning failure and a validation rejection stay distinguishable in the log. A planner that itself times out is `TIMEOUT`; a database whose plan-only mode itself can't be entered (SQL Server only) is `UNSUPPORTED`, never silently treated as a pass. Also fixes issue #382: a connect-time failure now returns a `.FAILED` `DryRunResult` instead of propagating the driver's own operational-error class unhandled. **Not wired into `POST /ask`** — issue #375 tracks the remaining turn-flow wiring for validation, limit injection, dry run and execution together.

### Added

- `askwell.sql.dry_run.dry_run_sandbox_query`/`dry_run_connection_query`/`DryRunResult`/`DryRunReason`.

## 0.4.20 - 2026-09-19

`M4-SQL-VAL-105` — automatic row-limit injection, and the injected limit made visible in the disclosed SQL. `askwell.sql.limit.inject_limit` adds `Settings.sql_row_limit` (`ASKWELL_SQL_ROW_LIMIT`, default 1000, adjustable) to an already-validated read that has no top-level aggregate and no limit clause of its own, marking the added `LIMIT` with a discarded-on-reparse SQL comment (`/* Added by Askwell */`) so it reads visibly different from one the model wrote. An explicit limit — `LIMIT n` or the SQL:2008 `FETCH FIRST/NEXT ... ROWS ONLY` form — is left untouched regardless of size. `result_was_truncated(row_count, limit)` labels a result landing exactly on the limit the same as one that exceeded it. Fixes two defects found in an earlier, unmerged attempt at this ticket: the injected-limit audit record now goes to `audit_interactions` rather than `audit_decisions` (#372), and a `FETCH FIRST/NEXT` clause is now recognised as an existing limit rather than silently overwritten (#371). **Not wired into `POST /ask`** — `M4-SQL-VAL-106` (the `EXPLAIN` dry run) is the remaining safety layer before a generated, validated, limited query can reach a real turn.

### Added

- `askwell.sql.limit.inject_limit`/`_inject_limit_sync` — row-limit injection on the parsed tree, never the query text.
- `askwell.sql.limit.result_was_truncated` — whether a result may be showing fewer rows than exist.
- `Settings.sql_row_limit` (`ASKWELL_SQL_ROW_LIMIT`, default 1000).

### Changed

- `askwell.sql.validate._DIALECTS` renamed to the public `DIALECTS`, shared with `askwell.sql.limit`.

## 0.4.19 - 2026-09-19

`M4-CONN-BE-099` — connection health and three distinguishable query-time failures. A live connection is now probed periodically (`ASKWELL_CONNECTION_HEALTH_CHECK_SECONDS`, default 60) and on demand, and a query against one now fails as `ConnectionUnreachable`, `CredentialsRejected` or `QueryRejected` rather than a raw driver exception — three different fixes, three different messages, none of them resembling a zero-row result. Every outcome runs through one transition rule (`connections._record_health_transition`) that writes a decisions record only on a real `ready`↔`attention` change, closing issue #360 by construction: the periodic check never calls `record_introspection` at all, so the unbounded-decisions-row failure mode it named cannot occur here.

### Added

- `askwell.connections.check_connection_health` — a metadata-only probe (reuses `probe_connection`) shared by the periodic cron and the library's on-demand reconnect action.
- `askwell.connections._record_health_transition` — the one place a `connection_health_lost`/`connection_health_recovered` decision is written, gated on a real status transition; also updates `sources.last_healthy_at` on every successful probe regardless.
- `askwell.worker.check_connections_health` — a cron job probing every `ready`/`attention` connection source.
- `askwell.sql_execute.ConnectionUnreachable`/`CredentialsRejected`/`QueryRejected` — the three distinguishable query-time failures on a live connection, each also driving a health transition immediately rather than waiting for the next periodic check.
- `POST /sources/{source_id}/reconnect` — synchronous on-demand health check for the library.
- `sources.last_healthy_at` (migration `9d4e7a2c1b58`), surfaced in the ingestion coverage snapshot the library reads.
- `ASKWELL_CONNECTION_HEALTH_CHECK_SECONDS` (default 60).

### Changed

- `askwell.sql_execute.execute_connection_query` takes a `source_id` and classifies every engine's connect/execute failure into one of the three types above instead of letting the driver's own exception through.

## 0.4.18 - 2026-09-18

`M4-EVAL-TEST-112` — the text-to-SQL and SQL-safety eval suites. Forty execution-matched text-to-SQL tasks (`eval/suites/text_to_sql.v1.json`, `pass_bar: 0.80`) and ten SQL-safety tasks (`eval/suites/sql_safety.v1.json`, `pass_bar: 1.00`, no exceptions) run against a new fixture database (`eval/fixtures/sql/`) seeded through the real sandbox path (`eval/sql_fixture.py`). Text-to-SQL is scored by result-set equivalence, not query text (`eval/sql_eval.py::execution_match_score`); SQL safety is scored on `askwell.sql.validate.validate_query`'s own verdict alone, never on whether execution against the read-only sandbox role happened to survive an accepted write — the only way "a deliberately weakened validator fails the safety suite" stays true. `docs/decisions.md`, this date, has the full reasoning.

### Added

- `eval/sql_eval.py` — `run_sql_suite`/`run_sql_safety_suite` (`mode: "sql"`/`"sql_safety"`), driving the real `generate_candidate_query` → `validate_query` → `execute_sandbox_query` path.
- `eval/sql_fixture.py` — seeds a sandbox database with a five-table schema and one deliberately unguessable column (`orders.stat_cd`), resolved by a user-origin schema note the same way a clarification answer would be.
- `eval/fixtures/sql/schema.sql`/`seed.sql`, `eval/suites/text_to_sql.v1.json`, `eval/suites/sql_safety.v1.json`.
- `eval/tests/test_sql_eval.py` — pure scoring-logic tests, including a unit test proving a weakened validator fails a safety task.

### Changed

- `eval/suite.py` accepts `mode: "sql"`/`"sql_safety"`; `eval/bench.py` dispatches them.
- `scripts/dev.sh eval` now also joins the `askwell_sandbox` network and threads the three `ASKWELL_SANDBOX_*` variables through, needed by the two new suites.
- `.github/workflows/eval.yml` runs both new suites alongside the existing four.

## 0.4.17 - 2026-09-18

`M4-SQL-OBS-108` — the audit requirement for the SQL path: every query `askwell.sql.validate.validate_query` looks at, accepted or rejected, is now one `audit_interactions` record (`kind = "sql_query"`) carrying the engine, source, the query text in full (never truncated), whether it validated, the rejection reason where there is one, and `limit_injected`/`rows`/`duration_ms` — recorded as `None` honestly, since limit injection (`M4-SQL-VAL-105`) and execution are not wired to a live turn yet. This corrects `M4-SQL-VAL-104`'s own choice to record a rejection to `audit_decisions` instead, which `docs/audit-log.md` §7 already assigns to Interactions, not Decisions. New `askwell.sql.observability.sql_rejection_rate`, mirroring `askwell.observability.abstention_rate`'s own shape, for the ticket's own "a prompt change's rejection rate going from 2% to 18% is visible before any user complains" acceptance criterion. `docs/decisions.md`, this date, has the full reasoning.

### Changed

- `askwell.sql.validate.validate_query` now records every outcome (accepted and rejected) to `Store.INTERACTIONS` under `kind = "sql_query"`, with a new optional `source_id` parameter, instead of only a rejection to `Store.DECISIONS`.

### Added

- `askwell.sql.observability`: `SqlRejectionRate`, `sql_rejection_rate`.

## 0.4.16 - 2026-09-18

`M4-SQL-VAL-104` — the C2 gate: every model-generated query is parsed with `sqlglot` and rejected unless it is exactly one `SELECT`/`WITH` read, with no regex anywhere in the path. New `askwell.sql` package (`api/src/askwell/sql/`, the enforcement point `docs/architecture.md` already named for C2) with `askwell.sql.validate.validate_query`. Rejects more than one statement, any data-modifying or definition statement, a locking read (`FOR UPDATE`/`FOR SHARE`), `SELECT ... INTO` (a write dressed as a read), a named list of side-effecting function calls (`pg_terminate_backend`, `xp_cmdshell`, and similar — documented as necessarily incomplete, not claimed as complete coverage), and anything `sqlglot` cannot parse at all for the target dialect. Critically, the check does not stop at the top-level statement type: PostgreSQL allows a data-modifying CTE with `RETURNING` (`WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d`), which parses with `SELECT` at the top while deleting every row when run — the ticket's own "nesting to disguise a modification" edge case, made concrete. Every rejection walks the whole parsed tree (`Expression.find_all`), not just the root node, which catches this case the same way a top-level `DELETE` is caught. A comment hiding a second statement needed no special handling: `sqlglot`'s tokenizer discards comments before they become part of the tree, so they were never a distinct code path to defend. Every rejection is recorded to `audit_decisions` (`kind = "sql_rejected"`) with its reason and the full query text — an acceptance is not recorded, since a successful generation is already recorded by `askwell.agent.sql_generate`. Parsing runs under a new bounded wait, `ASKWELL_SQL_VALIDATION_TIMEOUT_SECONDS` (default 2s), separate from the existing database statement timeout — this one bounds the parser, not the database. `sqlglot>=25.0` (resolved to 30.18.0) is a new runtime dependency, MIT-licensed, ships its own type stubs. **Not wired into `POST /ask`** — the same "do not wire ahead of a dependency that does not exist yet" reasoning `M4-SQL-DB-107` and `M4-SQL-BE-103` both recorded about themselves, now in reverse: limit injection (`M4-SQL-VAL-105`) and the `EXPLAIN` dry run (`M4-SQL-VAL-106`) are the remaining layers before a generated query can safely reach a real turn.

### Added

- `askwell.sql` package; `askwell.sql.validate`: `RejectionReason`, `ValidationResult`, `validate_query`.
- `Settings.sql_validation_timeout_seconds` (`ASKWELL_SQL_VALIDATION_TIMEOUT_SECONDS`, default 2.0).
- `sqlglot>=25.0` runtime dependency.

## 0.4.15 - 2026-09-18

`M4-SQL-BE-103` — schema retrieval and SQL generation, the first ticket of the `SQL` epic and the whole database path's own start. New `askwell.agent.sql_generate`: `select_database_source` picks the one `ready` dump/CSV/connection source a question's SQL should be generated against — automatically when exactly one candidate's schema notes look relevant, asking rather than guessing when more than one does (also the honest answer for a question spanning two databases, which this module never attempts), and reporting "no databases" when none does or none exist at all. `generate_candidate_query` then retrieves the relevant schema subset — reusing `schema_notes` and `askwell.memory.retrieve_relevant_facts`'s existing lexical ranking rather than a second schema representation, bounded to 40 notes — and asks the model for one candidate query via a new versioned prompt, `agent/prompts/sql_generation.v1.md`, with the schema, notes and memory delimited as data, never instruction (C7), the same boundary `agent/compose.py`'s delimiting helpers (now shared with `agent/conflict.py` rather than duplicated) already enforce for a document answer. A question with no relevant schema at all is reported as such rather than forced into a query, so a caller can fall back to document retrieval. Every successful generation is recorded to `audit_decisions` with the query text, whichever source it targeted and what schema/memory it drew on — before any validation exists to look at it (`M4-SQL-VAL-104`, next). **Not wired into `POST /ask`** — the same reasoning `M4-SQL-DB-107` recorded about wiring itself in early: executing or showing a generated query before it can be validated would be exactly what C2 exists to prevent, so this module is exercised directly (27 new tests against a real Postgres) rather than reachable from a real conversation yet.

### Added

- `askwell.agent.sql_generate`: `DatabaseSource`, `SourceSelection`, `GeneratedQuery`, `GenerationResult`, `list_database_sources`, `select_database_source`, `compose_sql_generation`, `generate_candidate_query`.
- `agent/prompts/sql_generation.v1.md`.
- `agent.compose.flag_injection_text`, `confidence_label`, `delimit_memory_facts`, `delimit_schema_notes` — extracted from `agent.conflict` so `sql_generate` can reuse the same C7 delimiting rather than a second copy.

### Changed

- `agent.conflict` imports its memory/schema-note delimiting from `agent.compose` instead of defining its own; behaviour unchanged (`test_conflict.py` passes unmodified).

## 0.4.14 - 2026-09-18

`M4-SCHEMA-BE-102` — closes issue #365. A stale schema note (`M4-SCHEMA-ING-101`) is now excluded outright from generation: `askwell.memory.retrieve_relevant_facts` — the one retrieval path both document answers and database question-answering draw schema-notes context from — filters `AND NOT stale`, tightening `-101`'s in-prompt caveat, which stays in `agent.conflict._delimit_schema_notes` as defence in depth but is no longer reachable through the one production caller. `get_active_schema_notes` is unchanged, so the library and memory screens still see a stale note.

A stale note now says *why*: new `schema_notes.stale_reason` (migration `20260918_3f7c1a9e5d20_schema_note_stale_reason.py`) is `'possibly_invisible'` when the vanished table is one a Postgres permission change hid rather than dropped (`SchemaInventory` gained `omitted_tables`, the names `_build_postgresql_inventory` already computed internally and previously discarded, keeping only the count) and `'dropped'` otherwise — including on every other engine, where the two still cannot be told apart. And a stale column note carries `reattach_suggestion` — the new column name, set only when its table lost exactly one column and gained exactly one in the same introspection run, the one case a rename is unambiguous without guessing (never automatic).

`refresh_schema_attention` (`askwell.schema_introspect`) surfaces the count as the library's own needs-attention reason — "N schema notes refer to a table or column Askwell can no longer find" — moving a source to `attention` when any of its schema notes go stale and back to `ready` once none are, without overriding an unrelated `attention` reason (a dead connection, locked credentials). Wired into both places `write_schema_inventory` runs from a completed re-introspection: `connections._run_deep_introspection` (a live connection) and `schema_introspect.reintrospect_sandbox_source` (a dump or CSV source).

The fix path's third option: new `POST /memory/facts/schema_note/{id}/reattach` moves an active, user-supplied note to a new table/column position — `askwell.memory.reattach_schema_note`, reusing `write_schema_note`'s own invariant (a user-origin write retires whatever is active at the new position) rather than a raw `UPDATE`, and superseding the note it moved from, the same shape `correct_schema_note` already uses.

### Added

- `SchemaInventory.omitted_tables`; `askwell.schema_introspect.refresh_schema_attention`, `_stale_attention_reason`.
- `schema_notes.stale_reason`, `schema_notes.reattach_suggestion` (migration `20260918_3f7c1a9e5d20_schema_note_stale_reason.py`).
- `askwell.memory.reattach_schema_note`, `ReattachOutcome`; `POST /memory/facts/schema_note/{id}/reattach`.

### Changed

- `retrieve_relevant_facts` excludes a stale schema note from what it returns.
- `write_schema_inventory` sets `stale_reason`/`reattach_suggestion` alongside `stale`, and clears all three together when a position reappears.
- `MemoryScreenRow`/`SchemaNote` carry `stale_reason`/`reattach_suggestion` through to `GET /memory` and `get_active_schema_notes`.

## 0.4.13 - 2026-09-18

`M4-SCHEMA-ING-101` — schema notes from the clarification loop, for the unguessable half of what `M4-SCHEMA-ING-100` already introspects. New `askwell.schema_introspect.raise_unguessable_column_clarifications` scans a freshly-introspected inventory for columns whose name alone does not explain itself (`st_cd`, `rfq`, `dob` — any token three characters or fewer outside a small common-word allowlist) and raises a clarification for each, with a bounded value distribution and row count as evidence (`clarify.column_distribution_evidence`, built by `M3-RAISE-BE-071` and unused until now) — heaviest column first when the per-source cap trims the list. A primary key or foreign key column is never asked about; `describe_column` already states what it references. Answering one flows through the existing clarification-answer path unchanged and promotes the `schema_notes` row to `origin='user'`. Wired into all three points that already call `write_schema_inventory`: a live connection's initial introspection, a dump import, and on-demand re-introspection — PostgreSQL only for now, MySQL and SQL Server have no bounded value query wired up yet (issue #362).

Also closes issue #355: a `user`-origin schema note whose table/column position a re-introspection no longer finds used to be left completely untouched — still active, nothing distinguishing it from a note still describing a real column. New `schema_notes.stale` (migration `1e6f3b9c4a72`) is set on exactly that note instead of leaving it silent, and cleared again if the position reappears. `SchemaNote` (ORM model and `askwell.memory`'s retrieval dataclass), `get_active_schema_notes` and `retrieve_relevant_facts` all carry the flag through, and `agent.conflict._delimit_schema_notes` renders it into the query-generation prompt as an explicit caveat so a stale note is never presented as current fact (C5).

### Added

- `askwell.schema_introspect.raise_unguessable_column_clarifications`, `_is_unguessable_column_name`, `_sample_postgresql_column_distribution`.
- `schema_notes.stale` (migration `20260918_1e6f3b9c4a72_schema_note_stale.py`).

### Changed

- `write_schema_inventory` flags a `user`-origin note `stale` when its position disappears from a re-introspection, and clears the flag if the position reappears, instead of leaving it untouched either way.
- `agent.conflict._delimit_schema_notes` carries a stale note's caveat into the composed prompt.
- `ask.py`'s `fact_citation` event for a `schema_note` now includes `stale`.

## 0.4.12 - 2026-09-18

`M4-SQL-DB-107` — the independent read-only role and statement timeout: every generated query, once `M4-SQL-BE-103`/`VAL-104`–`106` exist to produce one, will execute as a role the database itself refuses a write from, with a 30-second `statement_timeout` per session — two safety layers independent of whatever `sqlglot` validation (C2) does to the query text. New `askwell.sql_execute.execute_sandbox_query`/`execute_connection_query` run a query as `askwell_sandbox_readonly` (sandbox, never the owner, C3) or a live connection's own already-write-probe-verified credential, on all three supported engines, with the timeout applied per session (Postgres `SET statement_timeout`, MySQL `SET SESSION MAX_EXECUTION_TIME`, MariaDB `SET SESSION max_statement_time`, SQL Server's connect-time `timeout`). A cancellation raises `StatementTimedOut`, naming the query and the timeout and suggesting narrowing it, and is recorded as a decisions row plus a local, never-transmitted counter. New `Settings.sql_statement_timeout_seconds` (`ASKWELL_SQL_STATEMENT_TIMEOUT_SECONDS`, default 30, adjustable). New `askwell.sandbox.verify_readonly_role` checks the readonly role's own attributes (`rolsuper`/`rolcreatedb`/`rolcreaterole`/`rolbypassrls`) at worker startup and refuses to start on a misconfiguration rather than falling back to a writable role — verified live: misconfiguring the role crash-loops the worker with the exact privilege named; restoring it resumes normally.

### Added

- `askwell.sql_execute`: `QueryResult`, `StatementTimedOut`, `execute_sandbox_query`, `execute_connection_query`.
- `askwell.sandbox.verify_readonly_role`, `SandboxRoleMisconfigured`.
- `Settings.sql_statement_timeout_seconds` (`ASKWELL_SQL_STATEMENT_TIMEOUT_SECONDS`), default 30.

### Changed

- `askwell.worker.startup` refuses to start if `askwell_sandbox_readonly` carries a privilege a read-only role must not have.

## 0.4.11 - 2026-09-18

`M4-SCHEMA-ING-100` — full schema introspection: types, keys and relationships, for a live connection and a loaded sandbox database (dump or CSV) alike, on connect, on import, and now on demand. New `askwell.schema_introspect` reads every table and view's columns, primary keys and foreign keys in bulk (one query per shape per engine, not one per table) for PostgreSQL, MySQL/MariaDB and SQL Server, and writes plain-language table- and column-level `schema_notes` — `Table orders. Columns: id, customer_id, total. Primary key: id. Foreign keys: customer_id -> customers.id.` and `orders.customer_id — integer, references customers.id.` — which the existing lexical retrieval (`askwell.memory.retrieve_relevant_facts`, bounded to 5 notes per question) already ranks by relevance; no new retrieval path was needed. Views and materialized views are introspected and labelled distinctly. Re-introspection updates rather than duplicates: an inferred note with an unchanged description is left alone, one with a changed description is superseded by its replacement, and a table or column no longer present is superseded with nothing to replace it — a user-supplied note is never touched by any of this.

Introspection always runs as a read-only role, never a more-privileged one: a live connection reuses the credential `M4-CONN-SEC-097`'s write-permission probe already verified is read-only; a sandbox database (dump or CSV) is read as the new `askwell_sandbox_readonly` role rather than the owner that loaded it, via a new `Settings.sandbox_readonly_password` (`ASKWELL_SANDBOX_READONLY_PASSWORD`) and `askwell.sandbox.readonly_url`. For PostgreSQL, a table the readonly role cannot see is detected (`pg_class` lists every table regardless of privilege; `has_table_privilege` on each says which are actually readable) and counted as `omitted_count` without being named — MySQL and SQL Server have no privilege-independent catalog to compare against, so `omitted_count` is honestly `None` for those two engines (issue #353).

New `POST /sources/{id}/reintrospect` re-introspects a `connection`, `dump` or `csv` source on demand — a new `reintrospect_source_job` dispatches to `connections.run_introspection` (which already handles reconnecting, whether just-added or long-`ready`) or `schema_introspect.reintrospect_sandbox_source` depending on the source's own kind.

Two real bugs, both caught only by testing against a real, restricted Postgres role rather than by review — `docs/decisions.md` has the full account. `information_schema.table_constraints`/`key_column_usage` silently named no primary key or foreign key at all for a role with plain `SELECT` and nothing more; fixed by reading `pg_catalog.pg_index`/`pg_constraint` directly, which carry no such extra gate. `askwell.connections.record_introspection`, unexercised more than once per source before this ticket's own on-demand re-introspection made that possible, wrote a second competing active table note on every repeat call instead of leaving an already-noted table alone; fixed.

Verified live against the running stack: a real PostgreSQL dump import and a real live connection to a second Postgres database both produced correct column/type/key/foreign-key `schema_notes`; adding a table to the live connection's database and calling the new endpoint made it appear, twice in a row, with no duplicate notes; a table with `SELECT` revoked from the readonly role was counted as omitted and never named.

### Added

- `askwell.schema_introspect`: `SchemaInventory`/`Table`/`Column`/`ForeignKey`, `describe_table`/`describe_column`, per-engine introspection, `write_schema_inventory`, `reintrospect_sandbox_source`, `dispatch_reintrospection`.
- `askwell.sandbox.readonly_url`.
- `Settings.sandbox_readonly_password` (`ASKWELL_SANDBOX_READONLY_PASSWORD`), required like `sandbox_owner_password`.
- `POST /sources/{id}/reintrospect`; worker job `reintrospect_source_job`.

### Changed

- `askwell.connections.run_introspection` and `askwell.dump_import.import_dump` each now run a deep-introspection pass after their existing shallow one; a failure in it is logged and recorded but never turns a working source back to `attention`.
- `askwell.connections.record_introspection` is idempotent on repeat calls — a table already carrying any active note is left alone rather than gaining a second one.

## 0.4.10 - 2026-09-18

`M4-CONN-SEC-098` — encrypting stored connection credentials at rest. `sources.config_encrypted` is now genuinely encrypted, not plain JSON: a new `askwell.crypto` module derives a key with HKDF-SHA256 over a per-install secret (32 random bytes, generated on first use, written owner-only to `Settings.install_secret_path` — the host-backed mount the inference socket already shares between `api` and `worker`, outside `postgres-data`) and encrypts with Fernet (AES-128-CBC + HMAC). `create_connection_source` encrypts before insert; `run_introspection` decrypts before ever opening a socket, so a lost or changed install secret is caught and reported as `credentials_locked` — the source moves to `attention` with a message that explicitly says the database was never contacted, distinct from `host_unresolved` or any other reachability failure. Key derivation takes an optional passphrase and folds it into the same HKDF call, so M7's passphrase can extend the key without re-encrypting or re-prompting for credentials already stored — this ticket's own forward-compatibility requirement.

Verified live against the running stack: a connection's `config_encrypted` is unreadable Fernet ciphertext (`gAAAAA…`, no plaintext password or host as a substring); the connection introspects and works normally on the original install; deleting `install.key` and re-running introspection reports `credentials_locked` with the re-entry message rather than a misleading network failure.

### Added

- `askwell.crypto`: `load_or_create_install_secret`, `derive_key`, `encrypt`, `decrypt`, and `CredentialsLocked`.
- `Settings.install_secret_path` (`ASKWELL_INSTALL_SECRET_PATH`, default `/run/askwell/install.key`).
- `ReasonCode` value `credentials_locked`.

### Changed

- `askwell.connections.create_connection_source` now takes `settings` and encrypts `config_encrypted` before insert.
- `askwell.connections.run_introspection` decrypts before probing and reports a locked credential as `attention` rather than attempting a doomed connection.

## 0.4.9 - 2026-09-18

`M4-CONN-SEC-097` — the write-permission probe, `docs/data-sources.md` §4 layer 1. `askwell.connections.probe_connection` now refuses a write-capable credential before either read check runs, on all three engines, by privilege introspection only — never by attempting a write. PostgreSQL: superuser (`pg_roles.rolsuper`), database-level `CREATE` (`has_database_privilege`), or a table-level `INSERT`/`UPDATE`/`DELETE`/`TRUNCATE` grant (`information_schema.table_privileges`). MySQL/MariaDB: `SHOW GRANTS FOR CURRENT_USER()`, parsed for a write privilege and the object it is scoped to. SQL Server: `IS_SRVROLEMEMBER('sysadmin')`, `db_owner`/`db_datawriter`/`db_ddladmin` role membership, or a write permission from `sys.fn_my_permissions`. Every refusal names the strongest permission found and its object (`These credentials have INSERT on \`orders\`. …`) and carries copyable, engine-specific SQL for a read-only user (`read_only_user_sql`) — Askwell never runs it. A new `probe_unreliable` reason code refuses the connection outright whenever the privilege-introspection query itself raises, on any engine, rather than assuming safe. A refusal is recorded as a `connection_write_refused` decisions row (engine, host, the permission named — never the credential) and increments a local, never-transmitted Redis counter, best-effort, the same tolerance `askwell.egress._record` has for a Redis hiccup.

`web/components/add/add-screen.tsx`'s stale "the refusal for a write-capable credential is not wired up yet" copy is gone, replaced by a rendered `remediation` block (a read-only, selectable `<textarea>`) on a `write_capable` refusal. `web/components/settings/connections.tsx`'s "write permissions not yet checked" line is corrected to "write access refused if found".

### Added

- Write-permission probe in `askwell.connections.probe_connection` for PostgreSQL, MySQL/MariaDB and SQL Server.
- `ReasonCode` values `write_capable` and `probe_unreliable`.
- `askwell.connections.read_only_user_sql` — copyable, engine-specific statements for a read-only user.
- `askwell.connections.record_write_probe_refusal` — the `connection_write_refused` decisions record and the local refusal counter.
- `ConnectOutcome.remediation`, surfaced through `POST /sources/connection`'s response and rendered on the add-source screen.

### Changed

- SQL Server's write check fails closed on an unreadable credential; the pre-existing SELECT-only read check for that engine is unchanged and still assumes read access on the same failure, a known asymmetry — `docs/decisions.md`, this date.

## 0.4.8 - 2026-09-18

`M4-CONN-FE-096` — the connection wizard for a live database, `docs/data-sources.md` §4, `docs/ux/add-source.md` §4. Adds `POST /sources/connection`: validates host/port/database/user before any socket opens, then attempts a real connection against PostgreSQL (`psycopg`), MySQL/MariaDB (`pymysql`) or SQL Server (`python-tds`), a minimal read check (a table listing plus a best-effort SELECT-grant check), and — on success — creates a `connection`-kind source and dispatches `introspect_connection_job` to record its table names as `schema_notes` and mark it `ready`. `askwell.connections.py` classifies every failure into one of five distinguishable reasons (`host_unresolved`, `connection_refused`, `network_blocked`, `timeout`, `auth_failed`, plus `permission_denied` for a connection that succeeds but cannot read), matched against each driver's own exception types and, for `psycopg`, its message text — never guessed from a support matrix. `web/components/add/add-screen.tsx` gained `ConnectionRoute` (engine/host/port/database/user/password, one submit, a heading per `reason_code`) and `ConnectionQueued` (the same "recorded, now runs in the background" shape `DumpQueued` already has, polling `/ingest`). Settings gained a "Connected databases" section (`web/components/settings/connections.tsx`) with its own count, deliberately not folded into the network-activity zero. The library lists a connection's read status honestly: "read access confirmed, write permissions not yet checked" — `M4-CONN-SEC-097` (the write probe) is not built, so nothing claims a check that did not run.

**What this does not do, on purpose.** The egress proxy still permits nothing (`docs/architecture.md` §5.1); building the permit-and-forward mechanism a live connection actually needs is out of scope here and filed as [#345](https://github.com/Rumeasiyan/askwell/issues/345) — reasoning in `docs/decisions.md`, this date. Proven live during this ticket: a connection to the sandbox Postgres (reachable because `api` already shares that network for C3) round-trips end to end; the identical request against a real external IP comes back `network_blocked`, and against a real external host name comes back `host_unresolved` — the second of which is itself a finding folded into #345, since DNS resolution for anything outside the container network fails the same way a genuine typo does.

### Added

- `POST /sources/connection` (`askwell.connections`, `askwell.sources.add_connection`) — validates, connects, and either creates a `connection` source or returns why not.
- `askwell.connections.probe_connection` and its three per-engine blocking probers, each returning one of five typed, distinguishable outcomes.
- `introspect_connection_job` (`askwell.worker`) — reconnects with the stored configuration, lists tables, writes `schema_notes`, marks the source `ready`.
- `ASKWELL_CONNECTION_PROBE_TIMEOUT_SECONDS` (default `5.0`).
- `web/lib/connection-source.ts`, `web/components/add/add-screen.tsx`'s `ConnectionRoute`/`ConnectionQueued`, `web/components/settings/connections.tsx`.

### Changed

- `ARRIVES["connection"]` flips from `"M4"` to `null` in `add-source.ts`, the same edit `M4-DUMP-FE-090` made for the dump route.
- `docs/ux/settings.md` §4 now states that a connected-database count is separate from the network-activity zero, and that a connection's read-only status is honestly "not yet checked" until the write probe exists.

## 0.4.7 - 2026-09-18

`M4-DUMP-FE-090` — the dump route on the add-source screen, `docs/ux/add-source.md` §3, C3. Adds `POST /sources/dump`: one file at a time, engine-detected server-side (`askwell.filetypes._dump_engine`, best-effort from the header) and routed three ways — a PostgreSQL dump is queued and handed to a worker (`askwell.dump_import.dispatch_import`, the same one-attempt nudge `askwell.ingest.dispatch` already uses); a MySQL or SQL Server dump is refused naming both routes out (connect live, or export as CSV); an engine `filetypes` cannot place at all is refused with a question rather than a guess. The calm sandbox statement from `docs/ux/add-source.md` §3 is rendered once on the route, never as a modal or a checkbox. `web/components/add/add-screen.tsx` gained `DumpRoute`, which asks for the file's folder the same way the files route does, then polls `/ingest` for the source's status to render queued/importing, imported, and failed (a cap abort and an ordinary load failure render identically — both are `status = 'attention'` with a specific `last_error`).

Fixes two bugs found while building this: a `.sql`/`.dump`/`.backup` extension no longer overrides content when deciding whether something is a dump at all — a prose file renamed to a dump extension is now refused as *unsupported*, not indexed as plain text and not told it is an unidentified dump either (issue #341). A compressed dump (`backup.sql.gz`) gets a dump-specific refusal naming decompression and the two live-data routes out, rather than the generic "unpack it and add what is inside" archive message, which made no sense for a single-file database export (issue #342).

`ARRIVES[Route.DUMP]` flips from `"M4"` to `None` in both `filetypes.py` and `add-source.ts` — the only edit `docs/decisions.md`'s `M1-ADD-BE-023` entry said this route would ever need once its screen existed. `docs/data-sources.md` §7's PostgreSQL-only decision is unchanged; MySQL and SQL Server dumps stay unsupported *as dumps*, by design, not by omission.

Issue #340 (a failed Redis enqueue at add time leaves a `dump` source stuck `queued` forever, since there is no reconcile sweep for `dump`/`table` sources the way `askwell.ingest.reconcile` covers documents) is not fixed here — `dispatch_import`'s own docstring names the gap, and the issue stays open as a follow-up. Building the sweep is a second background job, not "one route and three messages," which is this ticket's own stated granularity.

### Added

- `POST /sources/dump` (`askwell.sources.add_dump`, `AddDumpRequest`) — resolves one dump file against the nominated roots, detects it, and either creates a `dump` source and dispatches the import or returns why not.
- `askwell.dump_import.dispatch_import` — enqueues `import_dump_job` for a just-created dump source.
- `askwell.filetypes._dump_engine` / `web/lib/add-source.ts`'s `dumpEngine` — best-effort PostgreSQL/MySQL/SQL Server/unknown classification from a dump's header.
- `askwell.filetypes.REFUSED_DUMP_ENGINE_UNKNOWN`, `REFUSED_DUMP_COMPRESSED`, `REFUSED_DUMP_UNSUPPORTED`, and the MySQL/SQL Server refusal template — mirrored in `add-source.ts`.
- `web/lib/dump-source.ts` (`addDumpSource`) and `web/components/add/add-screen.tsx`'s `DumpRoute`/`DumpQueued`.

### Changed

- `filetypes.detect`/`add-source.ts`'s `detect`: a dump-extension file with content that does not look like a dump is refused as unsupported rather than falling back to the files route as plain text (issue #341); a `.gz` file whose stacked extension names a dump gets the compressed-dump refusal instead of the generic archive one (issue #342).
- `ARRIVES[Route.DUMP]` / `ROUTES` dump entry: `"M4"` → `null`. `SUPPORTED_SUMMARY` updated to match.

## 0.4.6 - 2026-09-18

`M4-CSV-ING-094` — load a CSV or spreadsheet into its own sandbox database as a real, queryable table, `docs/data-sources.md` §2, C3. `askwell.table_load.process_table_source` runs `askwell.table_infer`'s existing parse-and-raise step (`M4-CSV-ING-092`/`093`) and then creates the table: column names normalised into valid identifiers (the original recorded as an `inferred` schema note so a question naming it still resolves), a column `table_infer` could not resolve with confidence loaded as `text` verbatim rather than coerced, and every other row cast to its confirmed type with per-row failures collected by row number rather than dropped. Answering a `date_format` clarification now does something real: `askwell.reapply` calls the new `askwell.table_load.reload_source`, which rebuilds the table from the source file with every date-format answer applied so far, turning a `text` column that was waiting on an answer into a real `date`. The size and time caps are the same ones `M4-DUMP-VAL-089` already added, read through `askwell.dump_import`'s own settings rather than a second pair a user would have to discover. `askwell.sandbox` gained `unseal_owner`, symmetric to `seal_owner` — unlike a dump, a table source can need a further owner-privileged write long after it is `ready`.

### Added

- `api/src/askwell/table_load.py` — `create_table_source`, `process_table_source`, `load_source`, `reload_source`, and the identifier/type/cast logic underneath them.
- `askwell.sandbox.unseal_owner` — re-grants the owner role's `CONNECT` on a database `seal_owner` sealed, for a reload's own write window.
- `worker.import_table_job`, registered with `WorkerSettings`.
- `askwell.table_infer.TableInference.rows` — the parsed data rows themselves, so loading does not re-parse the file a second time.

### Changed

- `askwell.reapply._process_item`/`run_job` now read a clarification's `trigger` and call `table_load.reload_source` when a `date_format` answer promotes a table source's schema note.

## 0.4.5 - 2026-09-18

`M4-DUMP-VAL-089` — size and time caps that abort a dump import and drop the sandbox, `docs/data-sources.md` §3, C3. Default 5 GB / 10 minutes, both user-adjustable and enforced *during* the load, not checked once at the start: `askwell.dump_import._load_blocking` runs a watchdog thread alongside `psql` that polls the sandbox database's own loaded size (`pg_database_size`, not `dump_path`'s size on disk — a dump that is small as a file but expands once loaded is exactly the case a file-size check would miss) and the elapsed wall clock, killing `psql` the instant either cap is crossed so a statement already running server-side is terminated rather than waited on. `import_dump`'s existing failure path (drop the sandbox database `WITH (FORCE)`, mark the source `attention`, record `dump_import_failed`) handles a cap breach the same way it handles a bad dump, with `cap` added to that audit payload so "how many imports were aborted for a cap" stays a query over `audit_decisions` rather than a separately maintained counter.

### Added

- `askwell.dump_import.get_dump_size_cap_bytes`/`set_dump_size_cap_bytes`, `get_dump_time_cap_seconds`/`set_dump_time_cap_seconds` — settings-table-backed, same shape as `askwell.clarify`'s clarification cap; every change is a `dump_cap_changed` decisions record.
- `askwell.dump_import.DumpCapExceeded` — names which cap (`"size"`/`"time"`) and the limit in force.

### Changed

- `askwell.dump_import._load_blocking` now takes the sandbox admin URL, database name and both caps, and runs a background watchdog thread for the life of the `psql` subprocess.

## 0.4.4 - 2026-09-18

`M4-DUMP-ING-088` — import a PostgreSQL dump into its own sandbox database, `docs/data-sources.md` §3, C3. `askwell.dump_import.import_dump` creates a fresh sandbox database, streams the dump into `psql` as `askwell_sandbox_owner` (`--set ON_ERROR_STOP=1`, so a statement the restricted role cannot run — creating a role, a tablespace — aborts the whole load rather than partially applying it), introspects the loaded table names, and on success seals the owner role off the database (`askwell.sandbox.seal_owner`, closing issue #330) before marking the source `ready`. Any failure drops the sandbox database outright and records the reason on the source; a load interrupted by a stack restart is reclaimed at worker startup (`dump_import.reclaim_interrupted`), alongside the existing orphan sweep. Full schema indexing (types, keys, relationships) is `M4-SCHEMA-ING-100`, not this ticket.

### Added

- `api/src/askwell/dump_import.py` — `create_dump_source`, `import_dump`, `reclaim_interrupted`.
- `askwell.sandbox.owner_url`/`seal_owner` — the owner role's DSN for one database, and revoking its `CONNECT` once a load succeeds.
- `worker.import_dump_job`, registered with `WorkerSettings`; worker startup now also reclaims a dump import a dead process left mid-load.
- `Settings.sandbox_owner_password` (`ASKWELL_SANDBOX_OWNER_PASSWORD`), required — the credential the owner role authenticates with.
- `postgresql-client` in the API image, for `psql`.

### Security

- Issue #330 closed: the shared owner role can no longer reach a database it loaded once that load finishes, so the role running the next dump's content cannot reach an earlier one.
- The import path is enforced onto the sandbox instance by configuration (`settings.sandbox_database_url`), never Askwell's own database — C3.

## 0.4.3 - 2026-09-18

`M4-DUMP-DEPLOY-087` — the sandbox Postgres instance for untrusted dumps, `docs/data-sources.md` §3, C3. A separate `sandbox` container (`compose.yaml`), on its own network with no route to Askwell's own database or the egress proxy, joined only by `api` and `worker`. Two fixed roles — `askwell_sandbox_owner`, `askwell_sandbox_readonly` — created with no superuser, no `CREATEDB`, no `COPY ... TO PROGRAM`, and no large-object access (both the filesystem and client-side APIs). `askwell.sandbox.create_database`/`drop_database` create and drop one database per imported source, revoking `PUBLIC`'s default `CONNECT` on each explicitly since `CREATE DATABASE` does not inherit that from a template; both write `audit_decisions` rows. `reclaim_orphans` runs at worker startup and drops any sandbox database no live source claims — the exact state a crash mid-import leaves behind. Importing a dump (`M4-DUMP-ING-088`) and the size/time cap (`M4-DUMP-VAL-089`) are not in this ticket.

### Added

- `compose.yaml` — `sandbox` service, `sandbox-data` volume, `sandbox` network.
- `deploy/sandbox/10-roles.sh` — the two fixed roles and the instance-wide lockdown of `template1`/`postgres` and both large-object APIs.
- `api/src/askwell/sandbox.py` — `generate_name`/`InvalidSandboxName`, `create_database`, `drop_database`, `known_databases`, `reclaim_orphans`.
- `Settings.sandbox_database_url`/`sandbox_host_port`; a `sandbox` component in `askwell.health`.

### Security

- C3 structurally enforced: a role boundary and a network boundary, verified against a real, running instance rather than asserted.

## 0.4.2 - 2026-09-18

`M4-CSV-ING-093` — never infer silently between DD/MM and MM/DD, `docs/data-sources.md` §2. A date-shaped column whose numeric values do not disambiguate (no value's day/month slot exceeds 12) raises a discrete `date_format` clarification with two options, ranked second only to contradictions. Where a value's own shape rules one format out — a slot above 12 — the format is inferred silently and recorded in `schema_notes` with the disambiguating value as evidence. A column whose values disambiguate in *both* directions (some rows only valid day-first, others only valid month-first) is reported as malformed rather than asked about as if one format fit every row. ISO and named-month dates have nothing to disambiguate and raise no question, regardless of sample size.

### Added

- `askwell.table_infer.detect_date_format` and `DateFormatVerdict` (`DAY_FIRST`/`MONTH_FIRST`/`AMBIGUOUS`/`MIXED`/`NOT_APPLICABLE`) — the DD/MM-vs-MM/DD disambiguation `infer_column_types` now runs on every date-typed column.
- `date_format` clarification trigger in `askwell.clarify._TRIGGER_PRIORITY`, ranked second only to `contradiction` per `docs/memory-and-clarification.md` §8.

## 0.4.1 - 2026-09-18

`M4-CSV-ING-092` — CSV and spreadsheet parsing with type and header inference, `docs/data-sources.md` §2. Nothing is applied silently: every column lands in `schema_notes` as `origin='inferred'` with its confidence, and anything the parser cannot resolve on its own — a missing or blank header, a column mixing a thousands separator with a plain decimal, a merged `.xlsx` header cell — becomes a real `clarifications` row, capped and ranked the same way `askwell.clarify` caps document-derived candidates. A row count that disagrees with the rest of the file is reported by row number as malformed, never silently padded. Loading the inferred table into the sandbox (`M4-CSV-ING-094`) and the DD/MM-vs-MM/DD date rule (`M4-CSV-ING-093`) are both out of this ticket's scope — this only parses, infers, detects and raises.

### Added

- `api/src/askwell/table_infer.py` — `infer_csv`/`infer_xlsx` (encoding and delimiter detection, header-presence voting from column typing, per-column type inference with confidence) and `raise_table_inference`, which persists inferred columns as low-confidence `schema_notes` and raises `Candidate`s (`askwell.clarify`) as real `clarifications` rows, idempotent per source. `MalformedTable` reports a ragged file by row number rather than padding it.

## 0.4.0 - 2026-09-18

`M3-EVAL-TEST-086` — the memory-application eval subset: fifteen tasks at the 0.85 bar (`docs/build-plan.md`'s quality gate), the differentiator's first measurement. This is M3's last ticket — *it learns my material* is complete, 20 of 20, taking the `MINOR` per `AGENTS.md` §7.

### Added

- `eval/memory_apply.py`, `eval/suites/memory_apply.v1.json` — a `mode: "memory"` suite. Five "apply" tasks (a stored fact resolves which of two genuinely conflicting fixture documents is currently in force), three "supersede" tasks (the same, after correcting the fact once through `askwell.memory.correct_memory_fact`), four "no_invent" tasks (a topically-related but insufficient fact must not license an answer where the documents abstain), three "irrelevant" tasks (an unrelated fact must not derail an otherwise-grounded answer). Every task scores whether the memory fact was cited (`fact_citation` events), and a superseded fact still being applied is reported as `superseded_fact_still_applied`, distinct from plain `no_application`.
- Fixture facts seed through the real write paths: `askwell.review.answer_clarification` (a fixture `clarifications` row, answered) for "apply"/"supersede", then `askwell.memory.correct_memory_fact` for the supersession step; `askwell.memory.write_memory_fact(origin="manual")` for the free-standing "no_invent"/"irrelevant" facts. Idempotent per subject, same guard `eval.grounded.seed_corpus` uses for the fixture documents.
- `eval/suite.py`: `mode: "memory"`. `eval/bench.py` dispatches it. `.github/workflows/eval.yml`'s gate now runs `memory_apply.v1` alongside the other three suites.

## 0.3.20 - 2026-09-18

`M3-MEM-FE-084` — the memory screen's six interactions: Edit, Confirm, Delete, History, Filter, Add a fact. `docs/ux/memory.md` §4. Also closes issue #288, filed against `M3-STORE-OBS-077` and deferred to this ticket.

### Added

- `askwell.memory.confirm_memory_fact`/`confirm_schema_note`/`confirm_fact` — promote an inferred row to user-supplied in place, `origin` updated on the same row (`'correction'`/`'user'`) with no new row and no re-processing, since the value itself did not change. Confirming an already-user-origin row is a no-op reported as such. `POST /memory/facts/{fact_kind}/{fact_id}/confirm`.
- `askwell.memory.add_manual_fact` — manual entry: the same fact shape a clarification answer writes, `origin='manual'` the only difference. A subject that already has an active fact is never double-written — the existing fact is returned so the caller offers a correction instead (`docs/ux/memory.md` §4's own edge case). `POST /memory/facts`.
- `askwell.memory.delete_all_memory` — deletes every active row the screen shows, reusing `delete_memory_fact`/`delete_schema_note` per row so the #288 fix, the decisions record and re-processing all run exactly as a single delete would. Takes `expected_count` and refuses with `StaleMemoryCount` (409) if memory has changed since the count was confirmed. `POST /memory/delete-all`.
- `web/lib/memory.ts` — `confirmFact`, `addManualFact`, `deleteAllMemory`, `applyMemoryFilters`/`memorySources` (the three filters: inferred-only, by source, unused) and `deleteAllConfirmationCopy` (the ticket's own Validation Rule: name the count, say it cannot be undone).
- `web/components/memory/memory-screen.tsx` — every row now has Edit (inline textarea, supersedes on save), Confirm (inferred rows only) and Delete; a filter bar above the list; an "Add a fact" form that offers a correction instead of a competing fact on a duplicate subject; a "Delete all memory" control with the named-count confirmation.

### Fixed

- **Issue #288**: deleting a fact that is itself a correction no longer resurrects the value it superseded. `memory.superseded_by`/`schema_notes.superseded_by` are `ON DELETE SET NULL`, so deleting the active row previously left Postgres nulling the predecessor's `superseded_by`, making an already-corrected-away value active again. `delete_memory_fact`/`delete_schema_note` now re-point any row pointing at the target to itself before the delete — still `superseded_by IS NOT NULL` (never active again), still readable in history (`get_memory_screen`'s history query only checks `IS NOT NULL`, never the target), and no longer named by the row being deleted.

### Tests

- `api/tests/test_memory.py` — 17 new cases against a real Postgres: confirm promotes in place with no new row and no reprocessing decision; confirming an already-user fact and confirming a schema note; confirm-then-edit leaves two records in order; manual entry creates a `manual`-origin fact; a duplicate subject is offered back rather than double-written; delete-all removes everything and refuses a stale count; three cases for #288 (a memory correction, a two-deep chain, a schema-note correction — none resurrect the superseded value).
- `api/tests/test_memory_api.py` — 6 new cases: session required for confirm/manual-add/delete-all, unknown fact kind is a 404 on confirm, empty subject and negative `expected_count` are 422.
- `web/lib/memory.test.ts` — filter combinations, `memorySources` de-duplication and ordering, delete-all-memory's confirmation copy.
- Verified against the real stack: `scripts/dev.sh check` (556 passed/1 skipped) and `scripts/dev.sh test-db` (440 passed) clean; `scripts/dev.sh web-check` clean (222 tests, build, contrast, offline check); rebuilt the API image and exercised the live stack with `curl` — manual add, the duplicate-offered-as-correction response, confirm (no-op on an already-user fact), correct, and the #288 scenario itself: correcting a fact then deleting the correction left the subject with nothing active rather than resurrecting the original value; the stale-count guard on delete-all returned 409 against a wrong count and 200 against the right one.

### Known gaps

- No bulk confirm — an open product question per `docs/ux/memory.md` §7, unchanged by this ticket, and explicitly Out of Scope in it.
- No memory export/import across machines — not v1 (`docs/memory-and-clarification.md` §9).
- `GET /memory`'s path collision with the client-rendered `/memory` page (issue #313, filed against `M3-MEM-FE-083`) is unaffected by this ticket.

## 0.3.19 - 2026-09-18

`M3-MEM-FE-083` — the memory screen is real: one list, both fact kinds, the confidence marker, source and "used in N answers" per row, inferred facts sorted first. `docs/ux/memory.md` §2/§3/§5. Interactions (Edit/Confirm/Delete/History/Filter/Add) are `M3-MEM-FE-084`, out of scope here.

### Added

- `askwell.memory.get_memory_screen`/`MemoryScreen`/`MemoryScreenRow`/`MemoryHistoryEntry` — one read across `memory` and `schema_notes`, active rows only, each with its own supersession history nested in (the "later wins, earlier struck through" state) rather than a separate group header; "grouped by subject" turns out to mean one row per subject/position, since only one row per subject is ever active at a time. History is fetched in two queries total, not one per subject, so "hundreds of facts" (`docs/ux/memory.md`'s own edge case) does not become an N+1. Sort is inferred-first, newest-within-tier — the same precedence rule `get_active_memory_facts`/`get_active_schema_notes` already apply, made the default rather than left to the caller.
- `GET /memory` (`askwell.memory.register_memory`) — the screen's whole payload: `rows` plus `inferred_count` for the "N guesses to review" line.
- `web/lib/memory.ts` — the fetch, wire-to-camelCase mapping, and pure copy helpers (`originLabel`, `usageSentence`, `deletedSourceNote`, `inferredReviewSentence`).
- `web/components/memory/memory-screen.tsx` — replaces the `/memory` placeholder. Empty state teaches what memory is and links to the clarification queue (`docs/ux/memory.md` §5's own acceptance criterion); a populated list renders each row's marker, subject, source tag, value, origin/date/usage sentence, a deleted-source note where it applies, and struck-through history where a row has any.

### Tests

- `api/tests/test_memory.py` — 6 new cases against a real Postgres: inferred-first sort with an explicit count, usage count per row, an unused fact is shown rather than hidden, a general fact from a deleted source is labelled, a corrected fact carries its old value in `history`, a schema note's subject renders as `table.column` and never carries a deleted-source label.
- `api/tests/test_memory_api.py` — `GET /memory` requires a session, same shape as the existing chip routes.
- `web/lib/memory.test.ts` — new file: the pure copy helpers.
- Verified against the real stack: `scripts/dev.sh check` (lint, format, typecheck, 550 passed/1 skipped) and `scripts/dev.sh test-db` clean; `scripts/dev.sh web-check` clean (215 tests, build, contrast, offline check); rebuilt both images and hit the live stack with `curl` — an inferred fact and a user-supplied one from a named source sorted inferred-first with the source tag attached, matching the test above exactly.

### Known gaps

- `GET /memory` shares its exact path with the client-rendered `/memory` page, so a hard reload or a direct `curl` to that path gets the JSON payload, not the page shell — pre-existing in this codebase (`GET /clarifications` has the identical collision against `/clarifications`) and out of this ticket's scope to redesign; the rail's own links are client-side navigation, which never hits this path directly. Filed as issue #313, options and a recommendation included.
- No editing, confirming, deleting, history view, filtering or manual entry — all `M3-MEM-FE-084`, named Out of Scope in the ticket itself.
- No bulk confirm — an open product question per `docs/ux/memory.md` §7, not started.

## 0.3.18 - 2026-09-18

`M3-CORRECT-FE-081` — the memory chip: a fact used in an answer is now clickable, and correcting or deleting it from there actually sticks. `askwell.memory` had every write-side primitive this needs since `M3-STORE-BE-076`/`M3-CORRECT-BE-082`, but no HTTP surface — `docs/BRAIN.md`'s own note on `-082` said plainly that whichever of the chip or the memory screen started next would need one; this is that.

### Added

- `askwell.memory.register_memory` — three new routes: `GET /memory/facts/{kind}/{id}` (what a popover needs: the fact, its origin, date, how many answers used it, and — if superseded since — the current version), `POST /memory/facts/{kind}/{id}/correct`, `POST /memory/facts/{kind}/{id}/delete`. Registered in `app.py` alongside every other route module.
- `askwell.memory.correct_fact`/`delete_fact` — one dispatcher per action across both `memory` and `schema_note` kinds. `correct_fact` tries `correct_memory_fact`/`correct_schema_note` first and falls back to a fresh user-origin `write_memory_fact`/`write_schema_note` on `CannotCorrectInference` — the chip's "Correct" on an inferred fact is really "assert this instead", which is what the module's own docstring already said an inference has no other path for.
- `askwell.memory.get_fact_detail`/`FactDetail` — the popover's read, including the "already superseded" edge case (`current`, one level deep) and an exact `usage_count` from `fact_usage`.
- `web/lib/memory-chips.ts` — `applyFactCitation` folds `fact_citation` SSE events into per-claim chips (never grouped, unlike a citation card — a chip renders once per claim it supports); `fetchFactDetail`/`correctFact`/`deleteFact` call the new routes.
- `web/lib/ask.ts` — parses the `fact_citation` event `M3-APPLY-BE-079` already emitted but nothing on the frontend read.
- `AnswerProse` (`ask-screen.tsx`) renders a visible `MemoryChip` right after the claim it supports; clicking opens `MemoryFactPopover` — fact, origin, date, usage count, **Correct** (inline textarea) and **Delete**, wired to the routes above. The confirmation after a correction names what is being re-read (`Reprocessing.label`, already returned by the existing `_reprocess_subject` machinery).
- Confidence marker (`.ask-confidence-marker`, already in `globals.css` from the design system) reused on the chip itself — filled `--provenance` for a user-supplied fact, hollow `--inferred` for a guess.

### Tests

- `api/tests/test_memory.py` — 12 new cases against a real Postgres: correcting a user-origin fact/note from a chip, correcting an inferred one (asserts instead of raising), an unknown id, deleting by kind, `get_fact_detail`'s usage count and its superseded/current shape for both kinds.
- `api/tests/test_memory_api.py` — new file, HTTP-level: session requirement, UUID/kind validation, empty-value rejection — same shape as `test_review_api.py`.
- `web/lib/ask.test.ts` — a `fact_citation` frame parses correctly.
- `web/lib/memory-chips.test.ts` — new file: `applyFactCitation`'s dedup and per-claim grouping.
- Verified against the real stack: `scripts/dev.sh check` (lint, format, typecheck, 549 passed/1 skipped) and `scripts/dev.sh test-db` clean; `scripts/dev.sh web-check` clean (208 tests, build, contrast, offline check); routes exercised live with `curl` against a real fact — read, correct (supersedes, returns a reprocessing label), read again (shows `active: false` and the new `current`), delete, 404 on an unknown id.

### Known gaps

- No click-through in a real browser (ask a question, click the chip that lands, correct it, ask again) — native inference was not running this session, same precedent as `0.3.16`/`0.3.17`. The `fact_citation` event itself is already covered end to end by `M3-APPLY-BE-079`'s own `test_ask_api.py`; this ticket's own surface (the routes, the fold, the popover) is verified directly instead (see Tests), including a live `curl` round trip against the real routes.
- No history view from the popover — out of scope, named as a Known Gap in the ticket itself (belongs to the memory screen, `M3-MEM-FE-083`).

## 0.3.17 - 2026-09-18

`M3-APPLY-BE-079` — a memory fact or schema note can now be cited the same way a document passage is, attributed to the user and the date it was supplied, with the use recorded so "used in N answers" is a real number the moment the memory screen exists to show it.

### Added

- `askwell.agent.conflict.compose_conflict` numbers every retrieved `<memory-facts>`/`<schema-notes>` entry, continuing the citation index straight on from the document candidates' own `1..N` rather than a second marker syntax — one convention the model already knows (`[index]`), extended to a new range instead of taught twice.
- `askwell.ask._cite_claim` resolves an index past the document candidates against `fact_usage` instead of `citations`: one row per `(message_id, fact_kind, fact_id)`, de-duplicated so a fact cited by two claims in one answer still writes one row. A new `fact_citation` SSE event carries the fact's subject, text, origin, confidence and `created_at` — the attribution date the acceptance criteria ask for.
- `prompts/conflicting_sources.v1.md` — the "Memory and schema notes" section now teaches citing a fact or note by its index, and states the rule the ticket's Validation Rules ask for: a claim asserting content from the user's own material must cite a document; a claim that only explains what a term means may cite the fact or note directly.

### Fixed

- The uncited-claim check's `fact_usage` exclusion (`M3-APPLY-RET-078`) was dead code until this ticket — nothing populated the table. It now does, for real answers, for the first time.

### Tests

- `api/tests/test_conflict.py` — 2 new cases: facts and notes index correctly after N candidates, and index from 1 with no candidates at all.
- `api/tests/test_ask_api.py` — 2 new full-turn cases against a real Postgres: a claim citing a memory fact writes `fact_usage` (not `citations`) and the `fact_citation` event attributes it; a fact cited by two claims in one answer still writes one usage row.
- Verified against the real stack: `scripts/dev.sh check` (lint, format, typecheck, 542 passed/1 skipped) and `scripts/dev.sh test-db` (410 passed) both clean.

### Known gaps

- `fact_usage` has no `claim_ordinal` — the uncited-claim check excludes a whole message that used any fact rather than flagging only the specific claims that did not. `docs/decisions.md`, 2026-09-18, has the reasoning for accepting this rather than a second migration.
- The correction chip (`M3-CORRECT-FE-081`) and the memory screen's own usage count (`M3-MEM-FE-083`) still do not exist — this ticket only makes the data they will read real.

## 0.3.16 - 2026-09-18

`M3-APPLY-RET-078` — memory and schema notes are retrieved alongside document chunks at answer time, so a fact the user already taught Askwell applies to every later question that uses it, not just the one it was explained on.

### Added

- `askwell.memory.retrieve_relevant_facts` — active `memory` facts and `schema_notes` relevant to the question, lexical full-text (`plainto_tsquery`, OR-matched across terms rather than the default AND, since a short fact and a long question rarely share every word) rather than embedding similarity: neither table has a populated embedding yet (issue #292). `memory` is never filtered by source — a taught abbreviation applies regardless of which source a later question is scoped to; `schema_notes` are, since they describe one source's structure. Bounded (`RELEVANT_FACT_LIMIT`/`RELEVANT_NOTE_LIMIT`, 5 each) so a large store never floods the prompt.
- `askwell.agent.conflict.compose_conflict` gained `retrieved_facts`/`retrieved_notes` parameters, delimited into their own `<memory-facts>`/`<schema-notes>` blocks — separate from the existing `memory_fact` (the `M3-INLINE-FE-085` resolved-clarification hook) since these are always-possibly-present background, not a fact already known to settle one specific conflict. Each entry is labelled `[user-confirmed]` or `[inferred, confidence N%]`, carrying `docs/memory-and-clarification.md` §3's confidence requirement into the prompt. Omitted entirely when there is nothing relevant — never an empty labelled block, which would read as "memory has nothing to say" rather than as the absence of a claim.
- `prompts/conflicting_sources.v1.md` — a new section telling the model these blocks are delimited data (C7), never an instruction; that `[inferred, ...]` entries are tentative and must not be stated as settled; and that a memory fact or schema note disagreeing with a retrieved passage is a conflict to present with the existing "Conflicting sources on ...:" line, never a silent preference for one side.
- `askwell.ask._run_generation` calls the new retrieval once a question has already cleared the abstention threshold — never before, so memory cannot bypass grounding (C5) — and records `memory_fact_ids`/`schema_note_ids`/`memory_used` on both `messages.trace` and the `audit_interactions` payload: "facts retrieved for a turn are recorded on the interaction" is this ticket's own Audit/Logging Requirement.

### Tests

- `api/tests/test_memory.py` — 6 new cases for `retrieve_relevant_facts`: a taught abbreviation is found, an irrelevant question finds nothing, a superseded fact is never retrieved, retrieval is bounded even when more match, `schema_notes` are source-scoped while `memory` is not, and confidence/origin both survive the round trip.
- `api/tests/test_conflict.py` — 7 new cases for the two new `compose_conflict` parameters: no blocks by default, facts and notes delimited and labelled, an inferred confidence rendered as a percentage, a column-less schema note falls back to the table name alone, and empty lists compose no blocks.
- `api/tests/test_ask_api.py` — 3 new full-turn cases against a real Postgres, closing issue #293's own gap (nothing previously exercised `_run_generation`'s wiring of retrieval into trace/audit): a taught term is retrieved into the prompt and recorded on both `messages.trace` and `audit_interactions`; a question with no relevant memory records an honest empty list, never a fabricated id; an abstained turn never retrieves memory at all.
- Verified against the real stack: `scripts/dev.sh check` (lint, format, typecheck, 540 tests passed/1 skipped) and `scripts/dev.sh test-db` (408 passed, up from 393) both clean.

### Known gaps

- Retrieval is lexical full-text, not embedding similarity — issue #292, left open rather than folded into this ticket: neither `memory` nor `schema_notes` has a populated embedding, and building that (a migration, an `embed()` call on write, a cosine-similarity query) is sized as its own ticket once real signal shows lexical match is actually missing facts, per the issue's own recommendation.
- Citing a memory fact or schema note by claim, the way a document citation resolves to a chunk, is `M3-APPLY-BE-079`'s own scope — untouched here. The prompt tells the model plainly that citing memory this way is not yet supported.

## 0.3.15 - 2026-09-17

`M3-REVIEW-FE-075` — the clarifications screen's remaining states: none pending, ingestion still running, all answered, answered-and-re-processing, and capped. Closes #297, #299, #300.

### Added

- `web/components/clarifications/reapply-progress.tsx` — per-item re-processing progress, polled from `GET /reapply-jobs/{id}`. A failed job surfaces the first failed item's own `error` text and a `Retry` button (`POST /reapply-jobs/{id}/retry`) rather than the previous generic "stopped, not stuck" line with no reason (#299) — `askwell.reapply.get_job` already returned `items[].error`; nothing on the frontend read it until now. `ClarificationsScreen` tracks the active jobs an answer opens and keeps a card visible until the job reaches `done`, independent of the answered item's own 10-second undo window, so progress is not tied to a card that has already left the list.
- The completion state (`../ux/clarifications.md` §5, "All answered"): a session-local tally (`web/lib/clarifications.ts` `SessionTally`) accumulates what was answered and skipped in this browser tab. `completionSentence` names it honestly — "N skipped. Nothing re-read." when nothing was actually answered, never a congratulatory line for an all-skipped batch — and shows a table/document breakdown per `Reprocessing.kind` (#300) rather than collapsing everything into "documents": `askwell.review.Reprocessing` and `_reprocessing_summary` gained `kind: "table" | "document"`, derived from the evidence shape (`column_distribution` → table, everything else → document). No trigger built so far produces a table clarification, so this reads "document" in practice today; the field exists so the very first table trigger (M4) does not need a second migration of this shape. The banner shows for a fixed window (`COMPLETION_VISIBLE_MS`, 6s) then hands back to the plain empty state on its own.
- The capped state (`../ux/clarifications.md` §5): `askwell.review._capped_counts` reads `audit_decisions` for `clarification_capped` records directly, independent of `list_pending`'s own pending-only query, so a source whose entire raised queue has since been answered or skipped still gets a group — with no items, just the disclosure and a link to Memory (#297, the ticket's own named gap from when `-074` shipped). `GET /clarifications` now also returns the configured `cap`, so the banner names the real number ("Asking about the 5 that matter most") rather than a hardcoded one.
- A pending group for a source still mid-ingestion (`SourceCoverage.outstanding > 0`, read from the existing `subscribeIngest` stream) now says so — "Still indexing this source — already searchable" — rather than looking identical to a source that has finished.
- `POST /clarifications/{id}/answer` now returns `reapply_job_id` (`null` when nothing needed re-processing) alongside the existing `reprocessing` object, so the browser can open a progress card without a second round trip.

### Tests

- `api/tests/test_review.py` — 8 new cases: the configured cap is reported, a capped-only source gets a group with an empty item list, a capped source that still has pending items carries the count on the existing group, a deleted capped source stays hidden, and `_reprocessing_summary`'s `kind` for both the document default and a column-distribution table.
- `web/lib/clarifications.test.ts` — 9 new cases: `cappedSentence` names the real configured cap, `reapplyFailureReason` surfaces the first failed item's reason and is `null` when nothing failed, `completionSentence` breaks tables and documents out separately, is honest rather than congratulatory when everything was skipped, and notes a mixed answered/skipped batch; `hasSessionActivity`.
- Verified against the real stack: `scripts/dev.sh check` (lint, format, typecheck, 534 tests) and `scripts/dev.sh test-db` (399 tests, up from 393) both pass; `scripts/dev.sh web-check` (typecheck, lint, 203 tests, build, version/token/contrast/offline guards) passes. Live against a rebuilt `api`/`worker`: seeded a source with a `clarification_capped` decision record and no pending rows — `GET /clarifications` returned it as its own group (`"capped":1,"items":[]`), confirming #297. Answered a real clarification through `POST /clarifications/{id}/answer` — the response carried a real `reapply_job_id`; polling `GET /reapply-jobs/{id}` showed the queued chunk fail (no inference bridge running in this session) with `items[0].error = "The assistant is stopped."`, confirming the exact reason `ReapplyProgress` now surfaces (#299) rather than a generic line. Scratch rows removed afterward.

### Known gaps

- Undoing an answer does not roll back that answer's contribution to the session completion tally — a rare correction, and the tally is session-local scratch, not a persisted record.
- No trigger in `askwell.clarify` produces `column_distribution` evidence yet (M4's own scope), so the "N tables" half of the completion sentence is exercised by tests only, not by a real walkthrough.

### Human review — copy

Exact wording introduced by this ticket, per `../ux/clarifications.md` §5 and `docs/build-plan.md`'s quality gate:

- Capped: `"Asking about the {cap} that matter most. Askwell inferred the rest — you can review them in Memory."` (`cappedSentence`)
- Completion, something answered: `"{N} answered[, {M} skipped]. {breakdown} re-read."`, e.g. `"3 answered. 2 tables and 17 documents re-read."`
- Completion, all skipped: `"{N} skipped. Nothing re-read."`
- Ingestion note on a still-indexing group: `"Still indexing this source — already searchable."`
- Re-processing failure: `"Stopped, not stuck: {reason}."`

## 0.3.14 - 2026-09-17

`M3-INLINE-FE-085` — a blocking ambiguity is asked inline, in the conversation, instead of waiting in the queue.

### Added

- `askwell.inline_clarify.find_blocking` — whether a still-`pending` contradiction or document-identity clarification is relevant to the question just asked, matched by subject-named-in-the-question or a document its evidence names being among the retrieved candidates. Only these two triggers can block; an abbreviation or a poor scan never withholds a single confident answer. Returns the highest-ranked match plus a count of any others relevant to the same turn, which are deferred to the queue rather than asked in sequence. `askwell.clarify.raise_candidates` now stores `evidence.trigger` on every raised row so this can tell the two apart without re-deriving it from the evidence shape.
- `askwell.ask._run_generation` checks for a blocking clarification once retrieval clears the abstention threshold and before `compose_conflict` runs. A match emits a new `clarification` SSE event and pauses the turn (`_Turn.clarify_event`, an `asyncio.Event`) until `POST /ask/{message_id}/clarify/resolve` wakes it — the browser answers or skips through the ordinary `askwell.review` endpoints first, so there is exactly one path that writes a `memory` row, whether from the queue or inline. An answer is passed to `compose_conflict`'s existing (previously inert) `memory_fact` parameter, so the model resolves the conflict and writes "Resolved by memory: ..." instead of presenting both sides. A skip continues with a Python-computed default assumption (the newer-dated passage, or the newest document) appended to the answer as its own stated line, never silently assumed. `Stop` still works while paused. A browser that never answers leaves the clarification exactly where it already was — `pending` in the ordinary queue — and the turn paused indefinitely; nothing is lost.
- `web/lib/ask.ts` gained the `clarification`/`clarification_resolved` SSE event types and `resolveInlineClarification`; `ask-state.tsx`'s `AskTurn` gained `blocking`. `ask-screen.tsx`'s new `InlineClarification` renders the same subject/question/evidence/options anatomy the queue screen uses (`EvidenceBlock`, exported from `clarifications-screen.tsx` rather than duplicated) and calls the same `answerClarification`/`skipClarification` before resolving. `AnsweredContent` now renders the `Resolved by memory:` line `parseAnswerAnnotations` already parsed but nothing rendered.

### Tests

- `api/tests/test_inline_clarify.py` — `find_blocking` against a real Postgres: a contradiction and a document-identity ambiguity relevant by subject or by document overlap, an unrelated pending one that does not match, a non-blocking trigger (abbreviation) that never blocks, an answered clarification that stops matching a later turn, two relevant ambiguities in one turn deferring the second, and `default_assumption` for both trigger kinds.
- `api/tests/test_ask_api.py` — two new full-turn cases, driven the same way the existing stop test drives `_generate` directly: a relevant contradiction pauses the turn, answering through `askwell.review.answer_clarification` and resolving through the turn's own `clarify_event` completes the answer with `memory_fact` in the composed prompt and a `Resolved by memory` line in the stored content; skipping continues and states the assumption used.
- `web/lib/ask.test.ts` — the two new SSE frame shapes parse.
- Verified against the real stack: `scripts/dev.sh check` (lint, format, typecheck, 535 tests) and `scripts/dev.sh test-db` (393 tests) both pass; `scripts/dev.sh web-check` (typecheck, lint, 196 tests, build, version/token/contrast/offline guards) passes.

## 0.3.13 - 2026-09-17

`M3-CORRECT-BE-082` — one correction path for both a chip in an answer and the memory screen, whichever gets built first.

### Changed

- `askwell.memory.correct_memory_fact`/`correct_schema_note`/`delete_memory_fact`/`delete_schema_note` now lock the active row (`FOR UPDATE`) before reading it, so two corrections of the same fact arriving close together serialise instead of interleaving. Correcting to the identical value is a no-op — no new row, no supersession record, nothing queued — and returns `Reprocessing(changed=False)` so a caller can say "nothing changed" rather than confirm work that did not happen. A real change now queues re-processing through `askwell.reapply` (the exact dependency resolution `askwell.review.answer_clarification` already uses, run with no clarification and no evidence) and returns a `Reprocessing`/`DeletionOutcome` naming what is being re-read, the same shape `AnswerOutcome.reprocessing` already gives the clarification path. All four functions' return types changed accordingly (`CorrectionOutcome`/`DeletionOutcome` replace a bare `uuid.UUID`/`None`).
- `askwell.reapply.resolve_dependencies`/`enqueue` accept `clarification_id=None` (fixed a latent bug: the conflict query's `id != :id` silently matched nothing when `clarification_id` was `NULL`, rather than every pending clarification) and `enqueue` accepts a pre-resolved `dependencies` list so a caller that already resolved them for its own summary — as `askwell.memory` now does — does not resolve them twice.

### Tests

- `api/tests/test_memory.py` — 9 new cases: same-value no-op for both a memory fact and a schema note, a sourceless fact resolving to nothing to re-process, a real correction queuing a `reapply_jobs` row naming the right subject/source/memory id, the ticket's own two-corrections-different-callers example (a clean three-value chain), deletion also queuing re-processing, a schema-note correction filtering out a `schema_note`-kind dependency it has no answer text to promote (an inferred note on a different table sharing the corrected column's name is left untouched), and correcting an already-deleted fact still raising `FactNotFound`.
- Verified against the real stack: seeded a source/document/chunk and a memory fact via `scripts/dev.sh psql`, ran two sequential corrections through `askwell.memory.correct_memory_fact` inside the `api` container (one standing in for the chip, one for the memory screen), and confirmed a clean three-value chain in `memory`, a `reapply_jobs` row per correction, and the second job closing `done` with zero items of its own since the chunk was already queued under the first — the existing de-duplication rule, not a new one.

## 0.3.12 - 2026-09-17

`M3-APPLY-ING-080` — answering a clarification now actually re-processes what it affects, closing #264. `M3-STORE-BE-076` (the dependency #264 was waiting on) merged to `main` earlier in the day; this ticket builds on it.

### Added

- `askwell.reapply` — dependency resolution and a durable re-processing queue, the same `arq`-dispatches/Postgres-records shape as `askwell.ingest`. `resolve_dependencies` reuses the exact evidence-derived document set `askwell.review._reprocessing_summary` already names in the confirmation toast (now exposed as `review.documents_named_in_evidence`), so what the user is told gets re-read and what actually does are the same set. Three kinds of item: `chunk` (re-embeds one passage of an affected document), `schema_note` (promotes a matching *inferred* `schema_notes` row to the user's answer, `origin='user'`), `conflict` (dismisses another still-pending clarification asking the same subject a different way — "re-resolve the contradiction" for the case dependency resolution can act on without guessing).
- `reapply_jobs`/`reapply_items` tables (migration `8ad5ca4aa1a1`). `reapply_items` is polymorphic by `kind`/`target_id`, matching `fact_usage`'s existing shape rather than three nullable foreign keys. A partial unique index on `(kind, target_id)` over `pending` rows is the de-duplication rule named in the ticket's own edge case — two answers naming the same chunk enqueue it once, `ON CONFLICT DO NOTHING`, and the job that loses the race simply reports fewer items rather than double-processing.
- `askwell.review.answer_clarification` now enqueues a `reapply_jobs` row in the same transaction as the `memory` write, and the answer route dispatches it to the worker after commit. `GET /reapply-jobs/{id}` (per-item progress) and `POST /reapply-jobs/{id}/retry` (resets `failed` items to `pending` and re-dispatches) are new — `../ux/clarifications.md` §5's "Answered, re-processing ... Per-item progress" and "Failures are visible with a retry".
- `askwell.worker.reapply_job` runs one job's pending items, each in its own short transaction — nothing locks a document or a source, so it stays queryable throughout. A failing item retries inline up to three times (matching `askwell.embed`'s own ceiling) before being marked `failed`; `askwell.reapply.resume`, called at worker startup like `askwell.ingest.resume`, returns an interrupted job to `queued` and re-dispatches it immediately, since nothing else reconciles a `reapply_job` on a timer.
- `askwell.review.undo_answer` now calls `askwell.reapply.cancel_pending_for_clarification`: not-yet-run items belonging to the undone answer's job are cancelled rather than left to apply a fact that no longer exists. An item already `done` by the time of the undo is a documented known gap, not reverted.

### Known gaps

- Dependency resolution is approximate by the ticket's own Assumption — every chunk of an affected document is queued, not a text-matched subset, and a `schema_note`/`conflict` match is by exact subject name only. Errs toward re-processing more rather than less, per the ticket.
- Undoing an answer whose re-processing has already completed some items (a chunk already re-embedded, a schema note already promoted) does not revert that work — only not-yet-run items are cancelled. Filed as a known limitation rather than built now, given the ticket's own upper-bound granularity.

### Tests

- `api/tests/test_reapply.py` — 18 cases against a real Postgres: dependency resolution for all three kinds (including the case-insensitive schema-note match and the deliberate exclusion of `user`-origin notes), de-duplication across two overlapping answers, `run_job` for each item kind, retry-to-exhaustion and the visible-failure/retry path, `resume`, and undo's cancellation.
- `api/tests/test_review.py`, `api/tests/test_models.py` updated for the new tables and the `AnswerOutcome.reapply_job_id` field.
- Verified against the real stack: seeded a schema-note ambiguity and a duplicate cross-source clarification via `scripts/dev.sh psql`, answered it through `POST /clarifications/{id}/answer` with a real session cookie, watched the worker log pick up and finish the job, and confirmed the inferred schema note was superseded by the user's answer and the stale cross-source clarification was dismissed — `GET /reapply-jobs/{id}` returned per-item progress throughout.

## 0.3.11 - 2026-09-17

`M3-REVIEW-FE-074` — save, skip, skip-all and undo wired into the clarifications screen, with the specific confirmation `docs/ux/clarifications.md` §4 requires.

### Added

- `ClarificationsScreen` now calls `answerClarification`/`skipClarification`/`dismissGroup`/`undoAnswer` (`web/lib/clarifications.ts`) against the existing `askwell.review` endpoints. Saving shows "Saved. Re-reading N documents." (never a generic toast), opens a 10s undo window, then the item leaves the list — all local state, no navigation. An empty answer is treated as a skip and says so. Skip-all removes a source's whole group at once.
- `askwell.review.answer_clarification` now returns a `Reprocessing` summary (count + label) alongside the memory id: the documents a passage/contradiction's own evidence already names, or `document_identity`'s `options`, falling back to every live document in the source when evidence names none. This is the count the confirmation shows — re-reading is still `M3-APPLY-ING-080`'s own no-op until that ticket lands, per this ticket's own Known Gap.
- Local, untransmitted counters for answered/skipped/dismissed (`getClarificationCounters`), same in-memory shape as `citations.ts`'s card-click counter (C1).
- Fixes #272: the screen now subscribes to `subscribeIngest` and merges freshly-fetched clarifications into local state (`mergeIncoming`) rather than fetching once on mount — a question raised mid-ingestion now appears without disturbing an answer already in progress, since a merge only ever adds items it does not already know about.

### Tests

- `api/tests/test_review.py` — five new cases covering the reprocessing summary's four evidence shapes and its fallback.
- `web/lib/clarifications.test.ts` — `savedConfirmation`, `isBlankAnswer`, and four `mergeIncoming` cases including the one issue #272 named (an item answered locally must not reappear just because a later fetch no longer lists it as pending).

## 0.3.10 - 2026-09-17

`M3-STORE-OBS-077` — the last two decisions-record shapes, and the transactional guarantee they all now share.

### Added

- `askwell.memory.delete_memory_fact`/`delete_schema_note` — the "deletion" record shape the ticket named as missing. Deletes the active row outright (there is no replacement to supersede-to) and writes `memory_deleted`/`schema_note_deleted` with a snapshot of what was deleted, in the same transaction.
- `askwell.review.dismiss_group` — skip-all for one source's group (`POST /sources/{id}/clarifications/dismiss`). Only pending items move to `dismissed`; one `clarification_dismissed` decisions record per item, so the dismissal signal (`docs/memory-and-clarification.md` §8) stays countable rather than one record per batch.
- `askwell.review.undo_answer` — reverses an answer within its window (`POST /clarifications/{id}/undo`, given the `memory_id` the original answer returned). Deletes the memory fact and reverts the clarification to `pending`; writes `clarification_answer_undone` as a new record rather than deleting or rewriting `clarification_answered`, per the ticket's own edge case. Refused (`CannotUndo`) if the fact has since been corrected or is otherwise no longer the active one — undoing then would silently discard whatever was built on it.
- `answer`, `correction` and `skip` already had their record shapes from `M3-STORE-BE-076`/`M3-REVIEW-BE-072a`; this closes the remaining two named in the ticket's Scope, and adds a `test_review.py` case that runs the ticket's own manual walkthrough (answer three, correct one, `askwell.audit.verify` reports an intact four-record chain) plus a fail-closed test against the exact statement sequence `answer_clarification` runs.

### Known gaps

- #288 — deleting a fact that is itself a correction resurrects the value it superseded, via the existing `superseded_by` `ON DELETE SET NULL` foreign key from `M3-STORE-BE-076`. Not reachable by a user until `M3-MEM-FE-084` builds the memory screen's Delete control; deferred to that ticket rather than fixed here.

## 0.3.9 - 2026-09-17

`M3-STORE-BE-076` (closing the ticket's own acceptance-criteria gaps found in review, #283, #284).

### Fixed

- #283 — `write_memory_fact`/`write_schema_note` now default `confidence` to `FULL_CONFIDENCE` for any user-origin write (`origin != "inferred"`) when the caller does not pass one explicitly, matching the ticket's own acceptance criterion ("Answering a clarification writes a fact with origin clarification and full confidence") and the module's own docstring. An explicit `confidence` argument still wins.
- #284 — `write_memory_fact`/`write_schema_note` now supersede *any* active fact/note for the same subject/position on a user-origin write, not only an inferred one. Previously a second `write_memory_fact`/`write_schema_note` call with a user-origin (bypassing `correct_memory_fact`/`correct_schema_note`) inserted a second simultaneously-active user-origin row instead of superseding the first, violating the ticket's own "two contradicting user answers" edge case for any caller that writes directly rather than through the correct-path functions.

### Known gaps

- #282 — `clarify.py`/`review.py` still write `memory`/`schema_notes` through their own inline `INSERT`s, not `askwell.memory`. Filed as its own ticket (`AGENTS.md` §4's ">3 files, agree first" applies), not rewired here.

## 0.3.8 - 2026-09-17

`M3-STORE-BE-076`.

### Added

- `askwell.memory` — the dedicated write-side module for `memory` and `schema_notes`: `write_memory_fact`/`write_schema_note` (an inference is discarded outright when an active user-origin fact already covers the subject/position, a user-origin write retires any active inference for the same one), `correct_memory_fact`/`correct_schema_note` (supersede an active user-origin fact with a new value — never in place, the old row stays readable), `get_active_memory_facts`/`get_active_schema_notes` (retrieval precedence: user-origin before inferred, newer before older within each). Every write, discard and supersession is an `audit_decisions` record (C6).
- `memory.source_id`, nullable (migration `2ae457a0587a`) — a general fact can now say which source taught it, and keeps saying so labelled as "from a deleted source" after that source is soft-deleted (`sources.status = 'deleted'`; `askwell.sources.delete_source` never hard-deletes the row).

### Fixed

- #258 — `test_writing_and_correcting_a_schema_note` now reads `superseded_by` back directly on the retired inferred note, rather than only inferring the retirement happened from a discard check that would also pass if the retirement `UPDATE` silently no-op'd.

### Known gaps

- `clarify.py`/`review.py` still write `memory`/`schema_notes` rows through their own inline `INSERT`s rather than this module — unchanged from before this ticket, tracked as a follow-up rather than rewired speculatively here (`docs/decisions.md`, 2026-09-17).

## 0.3.7 - 2026-09-17

`M3-REVIEW-FE-073`.

### Added

- **One clarification's full item anatomy** (`web/components/clarifications/clarifications-screen.tsx`, `docs/ux/clarifications.md` §3) — subject in mono, question in serif, evidence formatted per kind (value distribution with row count, a passage with its document and page, a contradiction's two passages, a poor scan's extracted pages) instead of raw JSON. A free-text answer field prefills with `current_inference` where Askwell has a guess; the current inference is echoed beside Save/Skip with the hollow `--inferred` confidence marker so the consequence of skipping is visible, and is absent (not a fake guess) when there is nothing to infer. Discrete choices (`options` present — a poor scan's re-scan/index-as-is, a document-identity or contradiction's file choice) render as equal-weight buttons instead of a text field. Evidence too sparse to show, or missing outright, renders "No evidence available" rather than an empty block.
- Save and Skip render with equal visual weight, per §3's own rule — neither is wired to the API yet (`M3-REVIEW-FE-074`, Out of Scope here).
- `.ask-confidence-marker` — the design system's §7 confidence marker (a 6px square, hollow `--inferred` or filled `--provenance`), its first real usage.

### Known gaps

- No link from a passage to its source: no evidence shape carries a `document_id`, only a filename — tracked as #280.


`M3-RAISE-BE-071`.

### Added

- **Evidence per raised clarification** — each of `askwell.clarify`'s four triggers now stores real, kind-tagged evidence with the question: `passage` (document, page, bounded excerpt) for an abbreviation or an ambiguous document identity, `contradiction` (both passages, their pages and dates) for disagreeing sources, `poor_scan` (extracted text per flagged page; `page_images` honestly named `"not available"`, tracked separately as #251) for a bad OCR pass. Every evidence dict carries `current_inference` — the same text that would have been written to `memory` had the candidate not been material enough to ask — so the answer field can prefill it (`docs/ux/clarifications.md` §3).
- **`column_distribution_evidence`** — the shared shape M4's column-ambiguity trigger will fill in with a query; no trigger calls it yet, since no data source exposes a column before M4.
- Evidence that cannot be captured (no locatable passage, no text on the flagged pages) never drops the question — it raises with `{"kind": "unavailable", "reason": ...}` instead, per the ticket's own edge case.
- Passages are bounded to 500 characters with an ellipsis; column value lists are bounded to the top 10 plus a `remainder_count` — a clarification record stays small regardless of corpus size.

## 0.3.5 - 2026-09-17

`M3-REVIEW-FE-072`.

### Added

- **`/clarifications`** — the queue as a single reviewable list, `GET /clarifications` grouped by source with a count per group and a total at the top. Not a wizard: no navigation between items, no confirmation step. Empty queue shows the teaching copy from `docs/ux/clarifications.md` §5 rather than "no items".
- **Left rail entry** — a `Clarifications` destination with a plain count badge (`useClarificationsTotal`, polled), never a red dot or a modal. Hidden entirely when the count is zero.
- **Post-ingestion prompt** — a one-line, dismissible banner in the shell's status-banner slot when the ingest queue goes idle with pending questions, so the badge is not the only way to notice. Shown once per idle transition, not repeated.
- Item answering (Save/Skip) and the full item anatomy are `M3-REVIEW-FE-073`/`-074`, Out of Scope here — items render subject, question and evidence, with no controls yet.

## 0.3.4 - 2026-09-17

`M3-REVIEW-BE-072a`.

### Added

- **`GET /clarifications`** — pending questions grouped by source, newest source first, each group carrying its source name, count and items (subject, question, options, evidence), plus a total across groups (`askwell.review.list_pending`). A source with `status = 'deleted'` never appears; a source with nothing pending produces no group.
- **`POST /clarifications/{id}/answer`** — writes a `memory` row (`origin = 'clarification'`, full confidence) and a `clarification_answered` decisions record in one transaction, then marks the item answered. Refused by name, not a second fact, for an item already answered. Answering a skipped item is allowed.
- **`POST /clarifications/{id}/skip`** — marks the item skipped and writes a `clarification_skipped` decisions record. No `memory` row: a skip is not an answer. Idempotent for an already-skipped item; refused for an already-answered one.
- Closes issues #257 and #268 (no `GET /clarifications` endpoint, filed independently by two build agents attempting `M3-REVIEW-FE-072` against a contract that did not exist).

## 0.3.3 - 2026-09-13

`M3-RAISE-BE-070`.

### Added

- **Memory and schema notes are checked before any candidate becomes a question.** A subject with a current fact — from this source or an earlier one, at any confidence — never reaches the clarification pass/fail tests; the existing fact applies instead, and nothing new is written over it (`askwell.clarify._known_facts`). A superseded fact never resurrects the question: only the current row (`superseded_by IS NULL`) is consulted, in `memory` first and `schema_notes` next.
- Each suppression is logged to the decisions store (`clarification_suppressed`) with the fact that was applied, and counted (`RaiseResult.suppressed`) — a local counter only, never transmitted (C1).

### Changed

- The abbreviation trigger's own inline memory pre-filter is gone; it goes through the same suppression path as every other trigger now, so it is logged the same way instead of silently disappearing.

## 0.3.2 - 2026-08-30

`M3-RAISE-BE-069`.

### Added

- **Clarification candidates are ranked and capped at 5 per source**, user-adjustable (`askwell.clarify.get_clarification_cap`/`set_clarification_cap`, backed by the `settings` table, defaulting to 5). Order: contradictions between sources, then ambiguous document identity, then abbreviations by corpus frequency, then low-confidence scans weighted by document size — date-format and unguessable-column triggers arrive with M4. Ties break deterministically by subject, so two runs over the same source choose the same five.
- `clarifications.rank` is now written for every raised question.
- Candidates that pass all three tests but rank below the cap are recorded to memory as low-confidence inferences naming their rank and the cap, distinct from a candidate that failed a test outright — nothing about the answer is invented either way.
- Changing the cap is a decisions-store record (`clarification_cap_changed`), never a silent settings write.

## 0.3.1 - 2026-08-30

Askwell notices what it does not understand about your material. `M3-RAISE-BE-068`.

### Added

- **Clarification candidates raised from an indexed source** - repeated abbreviations, filenames that look like versions of one document, and page-range references - each carrying what raised it so the question can name the evidence rather than asking in the abstract.
- `memory.origin` gains `inferred`, for a fact Askwell proposed rather than one the user stated.

### Fixed

- **A filename like `contract (2).docx` normalised to `contract (2)` while every other form normalised to `contract`**, so two copies of one document read as two different documents - the thing the normaliser exists to prevent. The `(2)` alternative sat inside a `\b...\b` group, and a word boundary needs a word character on one side; the character before the bracket is a space, so it could never match.
- **The migration adding `inferred` dropped a constraint under the wrong name.** `op.drop_constraint("ck_memory_origin", ...)` has Alembic's naming convention applied to it again, so it looked for `ck_memory_ck_memory_origin`, which has never existed. It failed every database test at setup - 276 errors whose cause is one missing `op.f()` in a file none of them mention.

## 0.3.0 — 2026-08-29

M2 — *it says when it doesn't know* — complete, 15 of 15. `M2-EVAL-DEPLOY-067`.

### Added

- `.github/workflows/eval.yml`: the 165-task quality gate now runs in CI, on a self-hosted runner labelled `askwell` (the maintainer's own machine — a hosted runner cannot comfortably load a model), triggered by a change to a prompt file, `retrieve.py`, `config.py`, a suite file, or a suite-mode module, plus manual dispatch.
- Runs the three suites that exist today (`grounded_qa.v1`, `abstention.v1`, `conflicting_sources.v1`) through `scripts/dev.sh eval`, publishes each summary to the job's step summary, and uploads the full JSON results as a 90-day artifact for before/after comparison.
- Self-heals the generation model weight from `models_catalog.py`'s registry-verified spec if missing; fails clearly, naming the reason, if the embedding or reranker weight is absent (no automated fetch source yet — issue #244) or the runner never picks the job up (30-minute timeout).
- A suite that fails for an infrastructure reason (model unavailable, broken fixture corpus) is distinguished in the job log from one that ran and scored below its `docs/build-plan.md` bar.

### Changed

- Naming this workflow's `eval` job as a required branch-protection status check on `main` — the step that actually blocks a merge with no recorded run — is a manual repo-settings step, not done by this change; noted in `docs/BRAIN.md`'s next-task line.

## 0.2.51 — 2026-08-29

Partial and conflicting-sources rendering on Ask. `M2-PARTIAL-FE-058`.

### Added

- The Ask screen now renders `askwell.agent.partial`/`conflict`'s composed answers as their own states rather than plain prose: an uncovered part is set off behind a `--rule-strong` left edge under its own "Not covered by your files" label, and a conflict gets a "Conflicting sources on `<fact>`" banner plus a resolve offer over the two cited positions — stated as not yet saved, since memory ships in M3.
- A conflicting answer's source cards (margin and inline) show their document's date and, when superseded since the answer streamed, that fact too. `GET /documents/{id}` gained `added_at`.
- Conflicting-sources cards are ordered by date (newest first) with a superseded source demoted to the end, never by the order the model happened to cite them in — `web/lib/document-dates.ts`'s `sortByDateAndSupersession`, fixing issue #226, which had blocked this ticket's first attempt.
- A local, untransmitted counter of conflicts presented (`recordConflictPresented`).

### Fixed

- Issue #226: conflicting-sources cards previously rendered in citation-stream order, which is model-preference order — the exact ordering `docs/ux/ask.md` §5's own Validation Rule forbids.

## 0.2.50 — 2026-08-28

The eval harness, offline. `M2-EVAL-TEST-063`.

### Added

- **`eval/bench.py`**: runs a named suite's tasks three times each against the configured model, over the native inference process's Unix socket only (no other network access), and reports mean and worst-of-3 per category — or strict pass/fail for a `pass_bar == 1.0` suite, so a near-perfect score on a suite that must be perfect never reads as fine. `RUNS_PER_TASK` is a fixed constant, not a flag, so a suite cannot be run once and reported as three.
- A model-unavailable failure (`InferenceUnavailable`) aborts the whole run with a named reason and writes no results file; a per-run failure (timeout, malformed output) is recorded on that run with its reason and the task continues.
- Results (`eval/results/*.json`, gitignored) carry the model actually loaded, the deployment profile, and every prompt file's version, for before/after comparison.
- New `scripts/dev.sh eval --suite <name>` command.
- `eval/suites/smoke.v1.json`, a two-task fixture proving the harness end-to-end — not one of the eight quality-gate categories (`M2-EVAL-TEST-064` onward).

## 0.2.49 — 2026-08-28

Deletion confirmation and the deleted-source citation card. `M2-DELETE-FE-062`.

### Added

- **Library deletion**: a "Delete" control on each source row (`DeleteControl`, `web/components/library/library-screen.tsx`) confirms inline, naming the source and stating the three facts a user would otherwise guess wrong — the file on disk is untouched, Askwell forgets its contents, old citations degrade honestly — before calling `DELETE /sources/{id}` (`deleteSource`, `web/lib/ingest.ts`).
- **Deleted sources stay listed, greyed, filterable.** The library's own `/ingest` snapshot (`askwell.ingest.coverage`) no longer excludes `status = 'deleted'` sources; a new `sources.deleted_at` column (migration `5f3a7c1e9d42`), set by `delete_source`, gives the library row its deletion date (`deletedSentence`, `web/lib/library.ts`). `LibraryFilters.showDeleted` hides deleted rows by default — `library.md` §4's "filtered out" is the resting state — with a checkbox to bring them back in.
- **Deleted-source citation card**: `ProvenanceMargin`/`InlineSourceCards` (`web/components/ask/provenance-margin.tsx`) check each cited document's live state with `GET /documents/{id}` and render a greyed, non-clickable "Deleted on `<date>`" card in place of the passage when it has been.
- **Deleted-source viewer state**: `DocumentViewer` renders `DeletedSourceNotice` (`web/components/documents/viewer-shared.tsx`) — "Deleted on `<date>`. Askwell no longer has the contents." — when `/documents/{id}` resolves a tombstone, and stays live: it subscribes to the same `subscribeIngest` stream the library watches, so deleting a source while its document is open in another tab lands the viewer on the deleted state within one poll interval rather than leaving stale content on screen.
- A local counter of confirmed deletions (`getSourceDeletionCount`, `web/lib/ingest.ts`) — in-memory only, never transmitted (C1), same pattern as `citations.ts`'s `cardClickCount`.

### Fixed

- **Issue [#231](https://github.com/Rumeasiyan/askwell/issues/231):** `GET /documents/{id}` (`askwell.documents.document_metadata`) 404'd a tombstoned document identically to an id that never existed. It now resolves the tombstone — `deleted`, `deleted_at`, `deleted_reason` — before the availability checks that assume a live document, which is what let the citation card and the viewer both render the deleted state honestly instead of a bare "not found." `GET /documents/{id}/file` still 404s a deleted document: the bytes are gone, and only the metadata route has a tombstone to resolve.

### Verified

- `scripts/dev.sh test-db` (263 passed: 2 new in `test_documents.py` for issue #231 — the metadata route resolving a tombstone, the file route still 404ing one; 1 new in `test_ingest_records.py` — a deleted source stays in the snapshot with its date; `test_sources_records.py`'s existing deletion test extended to assert `sources.deleted_at`). `scripts/dev.sh check` (529 passed, 1 skipped). `scripts/dev.sh web-check` clean (lint, typecheck, 177 lib tests including new ones for `showDeleted` filtering and `deletedSentence`, build, contrast, offline check).
- Exercised against the real stack: rebuilt the API image (the compose service has no source bind mount, unlike `scripts/dev.sh` commands) and ran the migration. `GET /documents/{id}` on a document tombstoned by an earlier manual `M2-DELETE-BE-061` walkthrough returned the deleted payload instead of 404; the same document's `/file` route still 404'd. `DELETE /sources/{id}` against a live source set `deleted_at` and left it in the `/ingest` snapshot with `status: "deleted"`; its document's `/documents/{id}` resolved to `deleted_reason: "source deleted"`. Browser-level rendering (greyed rows, the card, the viewer notice) was not visually checked — no browser tool is available in this session; the API contracts each of them reads are confirmed correct, and the component logic is covered by the type-checked build plus the pure-function tests.

## 0.2.48 — 2026-08-28

Tombstoned deletion that clears content and embedding. `M2-DELETE-BE-061`.

### Added

- **`DELETE /documents/{id}?reason=`** and **`DELETE /sources/{id}`** (`askwell.sources.delete_document`/`delete_source`): deleting a document clears its chunks' `content` and `embedding` in one statement and sets `deleted_at`/`deleted_reason`; the row and its chunks survive so an old citation still resolves to "deleted on `<date>`" rather than breaking. `superseded_by` is never touched by this — versions and deletions stay two separate facts. Deleting a source tombstones every live document under it the same way, deletes its `schema_notes` outright (nothing cites a schema note the way a citation cites a chunk), and leaves general memory untouched. Neither route touches the user's file on disk. Both are decisions records (`document_deleted`/`source_deleted`), so C6 holds — nothing is removed from the audit stores.
- A queued or running ingestion job for a document being deleted is cancelled (`ingest_jobs` row removed), and `askwell.ingest`'s own stage-transition writes (`_park`, `_finish`, `_fail`, and the `indexing` write in `process`) now all guard `deleted_at IS NULL`, so a job already claimed when the deletion runs cannot write a tombstoned document's status back to `ready`/`attention`/`queued`.

### Notes

- Retrieval already excluded tombstoned material (`deleted_at IS NULL AND superseded_by IS NULL`, `askwell.retrieve`) and the database already refused a cleared chunk keeping its embedding (`ck_chunks_cleared_content_has_no_embedding`, `M0-DATA-DB-014`) — both verified rather than rebuilt.

### Verified

- `scripts/dev.sh test-db` (261 passed, 15 new in `test_sources_records.py`: content and embedding cleared with the tombstone set, the file on disk untouched, a pending job cancelled, idempotent re-deletion, decisions records for both routes, a source deletion cascading to every live document under it including one mid-import, schema notes removed with general memory intact, `SourceNotFound` for an unknown or already-deleted source). `scripts/dev.sh check` (529 passed, 1 skipped; lint, format, typecheck clean).
- Exercised against the real stack: nominated `/tmp/askwell-demo`, added `client.txt`, `DELETE /documents/{id}?reason=...` — `psql` confirmed `status='deleted'`, `deleted_at` set, `deleted_reason` stored, the chunk's `content` and `embedding` both cleared, and `cat client.txt` on disk was unchanged. `DELETE /sources/{id}` set the source to `deleted`. Both appear in `audit_decisions`.

## 0.2.47 — 2026-08-28

Degrade to search when the assistant is unavailable. `M2-FAIL-FE-060`.

### Added

- **`GET /search`** (`askwell.retrieve.register_search`): retrieval with no composition and nothing persisted — no `messages` row, no `citations` row — for the moment there is no assistant to ask a question through. `askwell.retrieve.search` runs the same dense-plus-lexical, RRF-fused, reranked-if-possible pipeline `retrieve()` already does, except it catches `InferenceUnavailable`/`InferenceFailed` around the query-embedding call specifically and degrades to lexical search alone rather than failing the whole request — `retrieve()` itself is left unguarded there on purpose, since an unavailable assistant should fail an ordinary question. The response says `keyword_only` so the caller knows which happened.
- **Ask screen**: a "Search your files while the assistant is unavailable" panel (`DegradedSearch`, `web/components/ask/ask-screen.tsx`) appears above the composer whenever `/assistant` reports `available: false`, offering a keyword search box that calls `/search` and renders ranked passages with filename, page and a link that opens the source at that page (reusing `documentHref`/`pageLabel` from `lib/citations.ts`). Says plainly when a result set is keyword-only. Reads `useStatus()` directly rather than through a prop from `Shell`, so it disappears the moment the assistant reports ready again with no reload needed.
- `web/lib/search.ts`: the fetch and the snake_case-to-camelCase mapping (`parseSearchResponse`), tested in isolation in `lib/search.test.ts`.

### Notes

- The two other edge cases this ticket names — "restarting" reads differently from "unavailable", and the interface recovers mid-session with no reload — were already true before this change: `askwell.assistant._EXPLANATIONS` already gives `STARTING`/`CRASHED` their own headlines distinct from every other unavailable cause (`M0-MODEL-BE-020`), and `StatusBanner`/`useStatus` already poll and re-render reactively. Verified rather than rebuilt.
- **Deferred, filed as [#227](https://github.com/Rumeasiyan/askwell/issues/227):** the ticket's ingestion bullet — "embedding queues rather than fails" while the assistant is down, resuming with no manual step — contradicts the deliberate, tested `M1-INDEX-ING-032` decision that every stage failure, `InferenceUnavailable` included, is bounded by `MAX_ATTEMPTS` and then needs a manual retry (`docs/decisions.md`, 2026-08-28; `docs/states-and-edge-cases.md` §3's own "Embedding job failed after retries" row; `test_a_failure_exhausted_after_retries_is_visible_and_the_retry_works`). Left unimplemented rather than silently reversing that decision or breaking the test that encodes it.

### Verified

- `scripts/dev.sh test-db` (246 passed, 3 new in `test_retrieve_records.py`: dense-plus-lexical search when the assistant is up, degrading to lexical-only with `keyword_only` when it is down, and an honest empty result rather than an error when nothing matches). `scripts/dev.sh test` (529 passed, 1 skipped) and `scripts/dev.sh web-check` (173 web tests, 2 new in `lib/search.test.ts`; typecheck, lint, contrast, offline check all clean).
- Exercised against the real stack with the native inference process genuinely stopped on this machine: `curl /assistant` reported `available: false`; `curl /search?q=Meridian` returned the real chunk from an indexed test document with `keyword_only: true`; a Chrome screenshot of `/` shows both the existing global "The assistant is not running" banner and the new search panel rendered above the composer.

## 0.2.46 — 2026-08-28

Conflicting sources: present both, never pick one. `M2-PARTIAL-BE-059`.

### Added

- **`askwell.agent.conflict`**: `compose_conflict` builds the prompt for one turn once at least one candidate has cleared the retrieval threshold, from a new versioned prompt (`prompts/conflicting_sources.v1.md`, a superset of `partial_answer.v1.md`'s content) rather than a variant of it. When two or more retrieved passages give a materially different value for the same asked fact, the model presents both as ordinary cited claims and marks the presentation with a fixed, parseable line, `Conflicting sources on <the fact>:`. `split_conflict_answer` reads that convention back out, the same way `askwell.agent.partial.split_partial_answer` reads back `Not covered:` — both conventions coexist in the same composed text, since a conflict and an uncovered aspect are independent concerns.
- `askwell.ask._run_generation` now composes every non-abstained turn with `compose_conflict` in place of `compose_partial` — a question with no conflict parses to nothing and composes identically to before this ticket. `messages.trace` gained `conflict_detected`/`conflict_topic`, at both the turn level and the `compose` step; `audit_interactions` gained the same two on the interaction payload (no migration — both stores already carry flexible `jsonb`), satisfying the ticket's own "conflicts detected are recorded on the interaction."
- A memory-resolution hook, inert until M3: `compose_conflict` takes an optional `memory_fact` parameter that, when given, is delimited into the prompt as a `<memory-fact>` block the model is instructed to treat as authoritative over the conflicting passages, citing it as memory and recording resolution with a `Resolved by memory: <fact>.` line that `split_conflict_answer` also reads back (`resolved_by_memory`). Nothing calls it with a value in this milestone — there is no memory store yet to supply one from.

### Notes

- Supersession is respected without any new code: `askwell.retrieve` already excludes `d.superseded_by IS NOT NULL` from every candidate query (`M1`), so two candidates reaching this module are, by construction, both still current — a conflict here is never a live document against a version it has already replaced.
- Detection is prompt-driven, not a Python heuristic, for the same reason `M2-PARTIAL-BE-057` gave for partial coverage: there is no reliable way to tell "two passages disagree on substance" from "two passages phrase the same fact differently" without reading them for meaning, which the model is already doing while composing. Over-detection (flagging a wording difference as a conflict) is exactly as much a failure as under-detection per the ticket's own edge case, so the prompt is explicit that only a substance disagreement counts.
- **Deferred, filed as [#223](https://github.com/Rumeasiyan/askwell/issues/223):** the ticket's own edge case asks that a conflict where one side is low-confidence OCR text note that in the presentation. `Candidate` carries no OCR-confidence signal today — `document_pages.ocr_confidence` exists in the schema but is never selected into a candidate or delimited into any prompt — so the model can only note this if the passage text itself happens to say so. Threading that signal through `retrieve.py` was outside this ticket's stated touchpoints ("Prompt files; `messages.trace`") and its own granularity note ("one detection and one branch").
- Not measured yet: the conflicting-source eval subset with its 0.75 bar is its own ticket (`M2-EVAL-TEST-` series in `docs/backlog/M2-it-says-when-it-doesnt-know.md`) and has not landed, so detection quality is unmeasured — the same known gap the ticket itself names.

### Verified

- `scripts/dev.sh test` (529 passed, 1 skipped) and `scripts/dev.sh test-db` (243 passed — 2 new in `test_ask_api.py`: two passages disagreeing on the asked fact recorded as a conflict with both citations, and a single consistent answer never marked as one). `lint`, `typecheck`, `fmt-check` all clean.
- Native inference was not running on the host in this session (`/health` reports the inference component `stopped`), so this was verified through the same fake-inference-client, real-Postgres `TestClient` path `M2-PARTIAL-BE-057` used, not against a live model — recorded here rather than left unstated.

## 0.2.45 — 2026-08-28

Partial answers: answer the grounded part, name the gap. `M2-PARTIAL-BE-057`.

### Added

- **`askwell.agent.partial`**: `compose_partial` builds the prompt for one turn once at least one candidate has cleared the retrieval threshold, from a new versioned prompt (`prompts/partial_answer.v1.md`) rather than a variant of the ordinary answer prompt. A compound question is answered, with citations, for exactly the aspects the retrieved content supports; any aspect it does not support is never guessed at or smoothed into fluent prose — the model names it plainly on its own line, `Not covered: <the specific aspect>.`. `split_partial_answer` reads that convention back out of the composed text, the same way `askwell.agent.claims.segment_claims` already reads citation markers back out.
- `askwell.ask._run_generation` now composes every non-abstained turn with `compose_partial` in place of `compose` — a fully-covered question parses to nothing uncovered and composes identically to before this ticket, so this is additive, not a variation of the existing path with a flag on it. `messages.trace` gained `partial_coverage`/`uncovered_aspects`, at both the turn level and the `compose` step; `audit_interactions` gained the same two on the interaction payload (no migration — both stores already carry flexible `jsonb`).
- `askwell.agent.compose.delimit_candidates`/`flag_injection` are now shared, non-private functions — `askwell.agent.partial` reuses them rather than reimplementing C7's delimitation and injection-flagging a second time.

### Notes

- Structurally cannot blur into abstention: `compose_partial` only ever runs after `M2-ABSTAIN-RET-053`'s own threshold check has already decided the turn is not abstaining, so "every aspect uncovered" stays the abstention branch by construction, never a partial answer with an empty covered half.
- Aspect decomposition is prompt-driven, not a Python heuristic — there is no reliable way to tell "two aspects, one retrieved" apart from "one aspect, retrieved thinly" without asking the model doing the composition anyway, so detection and composition are one model call, and "marking the message as partial" is reading its own output back rather than a second judgement.
- **Found while verifying against the real stack, not fixed here:** the shipped generation model (`Qwen3.5-4B-Q4_K_M.gguf`) is a reasoning model and its `<think>` block is never stripped anywhere in the pipeline before `_run_generation` appends every streamed chunk to `turn.text`. Verified live, the model rehearsed `Not covered: termination notice period.` three times while drafting inside `<think>`, so `uncovered_aspects` came back with three duplicate entries instead of one written after `</think>`. This is a pre-existing gap in the whole answer pipeline — `segment_claims`'s citation markers are exposed to the identical risk and predate this ticket — not something introduced by or scoped to this one. Filed as [#220](https://github.com/Rumeasiyan/askwell/issues/220).

### Verified

- `scripts/dev.sh test` (510 passed, 1 skipped, up from 497) and `scripts/dev.sh test-db` (241 passed, up from 238 — 3 new in `test_ask_api.py`: a compound question with one uncovered aspect, every aspect covered composing exactly as before, every aspect uncovered still abstaining rather than going partial). `lint`, `typecheck`, `fmt-check` all clean.
- Against the running stack with native inference on the host and the real bundled weights (`bge-m3`, `bge-reranker-v2-m3`, `Qwen3.5-4B`): a real two-part question against a seeded chunk (payment terms covered, termination notice not) produced `partial_coverage: true` with citations on the covered sentences and a plain `Not covered: termination notice period.` line — confirming the mechanism works end to end with a real model, with the caveat above about the duplicate count from unstripped reasoning. A fully-covered question against the same corpus composed and stored exactly as it did before this ticket.

## 0.2.44 — 2026-08-28

The local abstention rate, computed from stored values, never recomputed. `M2-ABSTAIN-OBS-056`.

### Added

- **`askwell.observability.abstention_rate`** counts the `abstained` flag `M2-ABSTAIN-RET-053` already writes to every `audit_interactions` row over the most recent `window` questions (default 500), and reports how many it actually covered — a very long history still returns a bounded query rather than scanning the whole log. `.rate` is `None`, not `0.0`, when nothing has been asked yet, the same `NULL`-not-`0` reasoning `source_count` already settled per turn.
- No dashboard and nothing transmitted, both deliberately out of scope — the function is the whole surface, called on demand against the user's own log (C1).

### Notes

- Every candidate score, the threshold in force, and the near-miss were already stored per turn by `M2-ABSTAIN-RET-053`, not recomputed here — this ticket's own headline rule ("recomputation of a stored score is a defect") is enforced by `test_changing_the_threshold_later_never_alters_a_stored_turn` rather than by any new storage, since the storage already existed.

### Verified

- `scripts/dev.sh test` (497 passed, 1 skipped) and `scripts/dev.sh test-db` (238 passed, up from 231 — 7 new in `test_observability.py`) clean. `lint`, `typecheck`, `fmt-check` clean.
- `podman compose exec api askwell-verify` — both chains intact after the new tests' writes.

## 0.2.43 — 2026-08-28

Abstention renders as a deliberate state, not a blank answer. `M2-ABSTAIN-FE-055`.

### Added

- **`isAbstained`** (`web/lib/ask.ts`) is the one client-side signal an abstained turn has and an answered one never does: `completed`, no answer text, and a non-null `reason` — the server never streams the composed abstention message (`M2-ABSTAIN-BE-054`) as a `token` event, since the whole message is already known synchronously.
- **The abstained state** (`AbstentionState`, `ask-screen.tsx`) renders in place of the answer, in `--ink` and `--muted`, generous space, never `--alarm` — the situation on its own line, the rest of the composed message beneath it. Below it, in its own region, an **Add a source** action retains the question (via the same `fillComposer` pattern `context-rail.tsx`'s "Ask about this source" already uses) and navigates to the add flow — the region `M6.5-WEB-FE-186`'s escalation offer will later add two siblings to, never above the abstention statement (C10).
- **The provenance margin's own empty state for abstention** — "No sources — nothing in your files matched." — distinct from an ordinary uncited answer's "Nothing in this answer was cited."
- A past abstained turn collapses with no source count already, from `M2-ABSTAIN-BE-054`'s `source_count: null`; this ticket is what makes an *expanded* past abstained turn render the same state rather than nothing.

### Verified

- `scripts/dev.sh web-check` (lint, format, typecheck, 171 tests, build, version/token/contrast/offline checks) clean.
- No interactive browser walkthrough against the running stack — this environment has no browser tool. Verified by code inspection, unit tests on `isAbstained`, and a static build/typecheck pass instead.

## 0.2.42 — 2026-08-28

Abstention copy that proves the search happened. `M2-ABSTAIN-BE-054`.

### Added

- **`askwell.agent.abstain.compose_abstention`** builds the three-part abstention message — state the situation, prove the search happened, give the next action — as a pure template, no second model call: the nearest topic is the top scored candidate's own heading (or filename, when no heading exists), already in memory from the retrieval the turn already did. `askwell.ask._abstain_reason` now also returns the real passage/document/database counts the message proves the search against, queried with the identical join and `WHERE` clause `askwell.retrieve`'s own dense and lexical searches use.
- **A distinct empty-corpus variant** and a distinct still-indexing variant, neither of which claims a search happened or names a nearest topic — there is nothing to prove or name in either case.
- **`prompts/abstention.v1.md`**, versioned like every other prompt, states the standing rule this composition path must never cross: general knowledge is never substituted for a question about the user's own material (C5). `test_abstain.py` asserts the statement survives, the same shape as `test_compose.py`'s C7 assertions.
- `messages.content` and the audit record's own `answer` now carry the composed message for an abstained turn, rather than staying empty — streaming it as a `token` SSE event is `M2-ABSTAIN-FE-055`'s call to make, not this ticket's.

### Verified

- `scripts/dev.sh test` (497 passed, 1 skipped), `scripts/dev.sh test-db` (231 passed), `lint`, `typecheck` all clean.

## 0.2.41 — 2026-08-28

A below-threshold retrieval abstains instead of answering. `M2-ABSTAIN-RET-053`, issue 144.

### Added

- **C5's abstention branch, taken before composition.** `askwell.ask._run_generation` compares every reranked candidate's score against `Settings.retrieval_score_threshold` (default `0.65`); if nothing clears it, the turn ends without ever calling `compose()` or the model — there is no path from a below-threshold retrieval to a document-grounded answer. The threshold in force and every candidate's score, including the near-miss, are stored on `messages.trace` rather than recomputed later.
- **`askwell.retrieve.candidate_score`** turns whichever of a candidate's four scores is actually informative into one comparable to a `[0, 1]` threshold: a reranked candidate's raw, unbounded cross-encoder logit through a sigmoid, falling back to the real dense or lexical score for a candidate reranking never touched.
- **A distinct reason when a source-scoped question hits a source that is still indexing**, rather than reporting a generically empty corpus — `askwell.ask._abstain_reason` distinguishes `empty_corpus`, `source_indexing` and `below_threshold` by querying `askwell.ingest.coverage` for a scoped question and chunk existence otherwise. Final user-facing copy is `M2-ABSTAIN-BE-054`.
- **The interaction audit record gains `abstained` and `threshold`**, so an abstention is queryable from `audit_interactions` directly rather than only inferable from a zero citation count.

### Verified

- `scripts/dev.sh test` (488 passed, 1 skipped), `scripts/dev.sh test-db` (231 passed, up from 226), `lint`, `typecheck`, `fmt-check` all clean.
- Against the running stack with native inference on the host: a question with no candidate above threshold abstained (`status: "completed"`, `source_count: null`, near-miss score `0.0000164` stored under a `0.65` threshold); the same corpus's one real chunk answered normally for a matching question (score `0.9998`); `askwell-verify` confirmed both audit chains intact including the abstained interaction's `abstained: true`/`threshold: "0.65"` fields.

## 0.2.40 — 2026-08-28

The one download in the product runs on the host. Issue 192.

### Fixed

- **The model download no longer tries to reach the network from inside a container**, where it was refused by Askwell's own egress proxy — `403 Forbidden`, logged, exactly as designed. The API now writes a request into the models directory and reads progress back; the host supervisor that already runs `llama.cpp` performs the fetch, verifies the published sha256, and discards a file that does not match.
- **C1 gains no third exception.** An allowlist entry for `huggingface.co` would have cost the property that makes the proxy trustworthy — that no configuration exists which would let it forward. The containers holding the corpus keep zero route out.

### Verified

- `api/tests/test_model_fetch_host.py` loads the host script directly and exercises the fetch against a stubbed `urlopen`: a verified download lands, a checksum mismatch is discarded, a partial file resumes with the right `Range`, a server ignoring the `Range` restarts cleanly rather than appending, a cancel keeps what arrived and consumes its own flag, a dead network reports rather than raising, and a model already on disk is not fetched again.

## 0.2.39 — 2026-08-28

A second question stays in the same conversation. `M1-ASK-API-038`, issue 156.

### Fixed

- **`POST /ask` returns the conversation it used.** It accepted an optional `conversation_id` and resolved or created one server-side, and never said which — so the screen had nothing to send back and every question opened a fresh conversation. Both ids are now on every event, and `_load_finished` returns it too, because a browser reconnecting to a finished turn has no other way to learn which conversation it is in.
- **The ask screen sends it back.** `AskProvider` captures the id from the first event that carries it and puts it on every later question. Follow-up suggestions, conversation history and the whole `M1-CONV` surface were built on top of a thread that did not exist.

## 0.2.38 — 2026-08-28

The first-run sequence: what this is, machine check, model, first question. `M1-LIB-FE-052`.

### Added

- **`/welcome`** (`web/components/welcome/welcome-screen.tsx`) — the four-step sequence listed from the start: what Askwell is (offline, in-place indexing, stated up front), a machine check, the model download, and a first question. Shown until a first source is indexed, then never again (`web/components/shell/shell.tsx`'s `useWelcomeGate`); a "Skip setup" link is reachable throughout and goes straight to Ask.
- **`askwell.hardware.probe()`** — a basic hardware profile from `/proc/meminfo` and an `nvidia-smi`/`rocm-smi` presence check, standing in for the full probe (`M7-PROBE`) per the ticket's own stated assumption; falls back to `standard` with the reason stated when memory cannot be read at all.
- **`askwell.model_download.ModelDownloadManager`** and **`askwell.models_catalog`** — the model acquisition step: real progress and a real size/estimate, `Range`-based resume from whatever `<target>.part` already holds (so a restart or a click on Cancel then Resume are the same code path), sha256 verification, and a manual-file path for an offline or badly connected machine. Disk space is checked before any download starts. Registry-verified against Hugging Face on 2026-08-28: `bartowski/Qwen_Qwen3.5-4B-GGUF` (`light`/`standard`) and `bartowski/Qwen_Qwen3.5-9B-GGUF` (`accelerated`/`workstation`), both Apache-2.0 and ungated.
- **`GET /setup`, `POST /setup/model/start|cancel|verify-manual`, `POST /setup/skip`, `POST /setup/passphrase`** (`askwell/setup.py`) — the welcome screen's API surface. Skip and the passphrase decision (offered once, skippable, consequence stated; no encryption enforcement yet) are written to the `settings` table — its first real reader/writer — and recorded as `audit_decisions`.
- **`askwell.settings_store`** — thin get/set helpers over the `settings` key/value table.

### Known gaps, filed rather than worked around

- **Issue #191**: the downloaded model file lands at `Settings.inference_model_path` as resolved *inside the API container*, which the native inference supervisor (`M0-MODEL-DEPLOY-018`) does not share a mount with and resolves `~` differently. A completed download does not yet make the assistant reachable.
- **Issue #192**: the download call is refused by the egress proxy exactly as C1 and `docs/architecture.md` §5.1 design it to be — verified live (`model_download_failed error='403 Forbidden'`) — since model acquisition is not one of the proxy's two named, scoped exceptions. Recommendation on the issue is to move the fetch itself into the browser and keep the API's role to verification.

Both are architecture decisions outside this ticket's scope; `docs/decisions.md`, 2026-08-28, has the full reasoning.

## 0.2.37 — 2026-08-28

After an answer, up to three suggested follow-ups that fill the composer, not send. `M1-CONV-FE-180`.

### Added

- **`web/lib/follow-ups.ts`** — `followUpSuggestions` (pure): up to three questions derived from a completed turn's citations and answer text — one per distinct cited document (heading, when extraction found one; otherwise the same distinctive-term heuristic `askwell.suggestions` already uses server-side, applied to the answer), plus a fixed "How did you get this?" filling any remaining slot. No model call, matching the reasoning already settled for the empty-state corpus suggestions (`M1-LIB-FE-051`): this is exactly the moment a slow local model must not delay an answer already on screen. Returns `[]` for an abstained turn, a turn still running, or one with no citations at all — never padded. A local `recordFollowUpUsed`/`getFollowUpUsedCount` counter (in-memory only, C1) tracks use.
- **`web/components/ask/ask-screen.tsx`** — `FollowUpSuggestions`, rendered beneath a completed live turn's answer. Clicking one fills the composer via the existing `fillComposer` event; it sends nothing.

### Changed

- **`web/components/ask/ask-screen.tsx`** — `Composer`'s fill listener now asks before replacing a non-empty draft (`window.confirm`), rather than overwriting it silently. Applies to every caller of `fillComposer` (the pre-question corpus suggestions and the context rail's "ask about this source", not only this ticket's own follow-ups) since the draft-preservation rule is the composer's, not any one caller's.
- **`docs/states-and-edge-cases.md`** §2 — three new rows: suggested follow-ups after an answer, a suggestion clicked over an existing draft, and suggestion generation failing or having nothing to suggest.

## 0.2.36 — 2026-08-28

A collapsed turn opens back up, in place, with its stored answer and margin — and a source count opens it while bringing that margin into view. `M1-CONV-FE-179`.

### Added

- **`web/components/ask/ask-screen.tsx`** — `CollapsedTurn` is now interactive: clicking or pressing Enter/Space on its row toggles its own `expanded` state (colocated per turn instance, so expanding one never touches another), rendering the stored `answer` (`AnswerProse`, reused unchanged from `LiveTurn`) and its citations (`InlineSourceCards`, reused unconditionally rather than only below the breakpoint — see `docs/decisions.md`) directly beneath the row, with a `Collapse` control to close it again. `SourceCountBadge` gained an optional `onClick`, rendered as a nested real `<button>`: clicking it expands the turn (if not already) and scrolls its margin into view.
- **`web/components/ask/ask-screen.tsx`** — `TurnList`: the turn array now renders through a window (`conversationWindow`, `web/lib/ask.ts`) capped at `CONVERSATION_PAGE_SIZE` (twenty, `conversation.md` §7's settled starting value) from the newest turn backwards. A boundary row above the window offers "Load earlier turns" (also triggered by an `IntersectionObserver` on scroll) while more remain, and reads "Start of this conversation" once every turn has been revealed — never a silent truncation.
- **`web/lib/ask.ts`** — `conversationWindow` (pure): which turns are visible and whether more remain, given the full list and how many are currently revealed.

### Fixed

- Nothing — this ticket only adds interaction over turns `AskProvider` already held in memory; no prior behaviour changed.

### Deferred

- The "paging fails, offers to retry" edge case named in this ticket needs a real backend paged read of conversation history to fail against, and none exists yet — `conversation_id` is not threaded across turns (issue #156), so nothing survives a reload for a request to page through. Filed as issue #199 rather than simulated. See `docs/decisions.md`.

## 0.2.35 — 2026-08-28

Past turns collapse; an abstained turn shows no source count. `M1-CONV-FE-178`.

### Added

- **`web/components/ask/ask-screen.tsx`** — `TurnRow` now renders one of three shapes per turn: the single live turn (`LiveTurn`, the pre-existing full render, margin and all), a `QueuedTurn` waiting behind it, or a `CollapsedTurn` — question truncated to one line, the stored summary, and a source-count badge. `SourceCountBadge` renders a filled dot beside the number for an answered turn (`--provenance`, reserved for the count alone in that row) or an outlined, slashed circle beside "No sources" for one that abstained or failed — shape as well as colour carries the distinction (`docs/ux/design-system.md` §8). `TurnDivider` groups turns by calendar day (`docs/ux/conversation.md` §4).
- **`web/lib/ask.ts`** — `liveTurnId` (pure): the running turn if one exists, otherwise the most recently asked, so a question queued behind a streaming answer never displaces it as live. `dividerLabel` (pure): "earlier today" / "yesterday" / a calendar date between two turns' timestamps, `null` when they fall on the same day.
- **`AskTurn.createdAt` / `.summary` / `.sourceCount`** (`ask-state.tsx`) — captured from the `done` SSE event once generation finishes.

### Fixed

- **`api/src/askwell/ask.py`** — the `done` event carried only `status`/`reason`; `messages.summary` and `messages.source_count` (`M1-CONV-BE-177`) were written to the database but never reached the browser on any wire, which left this ticket with no way to render them without silently re-deriving a summary the ticket's own spec (`conversation.md` §6) forbids. Both `_run_generation`'s live `done` event and `_load_finished`'s reconnect replay now carry the same `turn_summary`/`failure_summary` already computed for the row, so the two are guaranteed to agree rather than being computed twice.

## 0.2.34 — 2026-08-28

A one-line summary and a source count, stored with every turn. `M1-CONV-BE-177`.

### Added

- **`askwell.agent.summarize.summarize_turn`** — the one-line summary and source count `docs/ux/conversation.md` §2 collapses a past turn to, produced once at composition time and written into `messages` (`summary`, `source_count`) in the same transaction as the answer, never recomputed on read. The source count is the number of distinct documents named by the turn's own citation rows — evidence actually cited, not a retrieval estimate. A turn with no citation rows abstained: `source_count` is `NULL`, never `0`, so scrolling back can tell "cited nothing" from "asked and answered from zero sources" (not currently reachable, but the schema does not conflate them). A stopped or length-truncated turn's summary is marked partial rather than silently describing a finished answer. A failed turn's summary names the failure. Summary generation itself never blocks the answer — a bug in it falls back to a summary derived from the question alone, logged as `ask_summary_failed`.
- Migration `22d97a766e29` — `messages.summary` (`text`, nullable) and `messages.source_count` (`integer`, nullable, `CHECK (source_count IS NULL OR source_count >= 0)`).

## 0.2.33 — 2026-08-28

The moved-or-renamed file state, distinct from deleted. `M1-VIEW-BE-049`.

### Added

- **`askwell.documents._availability`** — the open-time check behind `GET /documents/{id}` and `GET /documents/{id}/file`: a document whose recorded path no longer resolves is reported as `moved` (with the missing path and `missing_since`) when its nominated root is otherwise reachable, and as `root_unavailable` (with the root's own reason) when the whole root is unmounted, removed or unreadable — the two are never conflated, so a rename never reads as a deletion and an unplugged drive never reads as forty missing files. A file that reappears at its recorded path clears `missing_since` on the next open.
- **`POST /documents/{id}/relocate`** — repairs a moved document's path. Verifies the candidate path is inside a nominated root (`roots.covering`) and hashes it (`sources.fingerprint`); a matching hash updates `documents.path`, clears `missing_since`, and writes an `audit_decisions` record naming both paths. A mismatched hash is refused with the mismatch named, and the response points at adding the file as a new one instead of relocating to it — the ticket's own "moved and modified" edge case.
- **`askwell.ingest.sweep_missing`**, run every `ASKWELL_MISSING_CHECK_SECONDS` (default 300) by a new `worker.py` cron job — the same moved/root-unavailable detection as `_availability`, run on a timer so a moved file is caught even if nobody has opened it. `Coverage.missing` and `source_status`/`_attention_reason` extend the existing flagged-OCR pattern: a moved file makes a source `attention`, stays askable, and names how many files need relocating.
- **`web/components/documents/viewer-shared.tsx`** — `MovedFileNotice` (names the missing path, a typed-path relocate form using the same seam as root nomination) and `RootUnavailableNotice`, wired into `document-viewer.tsx`'s two new `moved`/`root_unavailable` states, replacing the generic "no longer at its recorded path" message both states previously shared.

## 0.2.32 — 2026-08-28

The source viewer's context rail: back to the answer, and citation stepping. `M1-VIEW-FE-048`.

### Added

- **`web/components/documents/context-rail.tsx`** — the viewer's right-hand rail: which answer and claim sent someone here (read straight out of the live `AskProvider` turn, `useAsk`), a "back to answer" control that lands on the exact claim, next/previous stepping across every passage the answer cited (including across documents, absent rather than disabled for a single citation), plain-text search within the source (`window.find`), copy passage with source and page appended, and "ask about this source" (scoped, via a new `sourceId` on `AskApi.ask`). Arriving with no turn in scope — the library, once it links here, or a reloaded tab that dropped `AskProvider`'s in-memory state — falls back to plain source context with no broken return, per the ticket's own edge case.
- **`SupersededBanner`** (same file) — "this version was replaced on `<date>`, with a link to current," resolving issue #141: `GET /documents/{id}` now reports `superseded_by` and `superseded_at` (the superseding document's own `added_at`, since `sources.py`'s `supersede()` already sets both in one transaction — nothing new to store).
- **`web/lib/citations.ts`** — `documentHref` grew an optional `origin` (`turnId`, `claimOrdinal`) carrying `turn`/`claim`/`chunk` query parameters; `stepCitations`, a pure function computing next/previous/current position among an answer's own citations, tested independently of any component.
- **`AskApi.ask(question, sourceId?)`** and `AskTurn.sourceId` (`ask-state.tsx`) — threads the context rail's scoped question through to `POST /ask`'s existing `source_id`, previously reachable only from the server. `fillComposer` gained a module-level pending slot so a scope set immediately before `router.push` survives the non-synchronous route change, the same gap `shell.tsx`'s `⌘K` shortcut already lived with.
- **`ReturnToClaim`** (`ask-screen.tsx`) — reads `?turn=&claim=` on the Ask screen and scrolls to the named `ClaimSpan` via a new `useScrollToClaim` (`leader.tsx`), reusing the leader-line registry rather than a second DOM lookup. Isolated behind its own `Suspense` boundary so the rest of the screen — the version line `scripts/check-version.mjs` reads, every corpus state — keeps prerendering in full under the static export rather than a fallback.

### Changed

- **Provenance cards now navigate with `next/link`, not a plain `<a>`** (`provenance-margin.tsx`) — a full page load would drop `AskProvider`'s in-memory turn entirely, which is fatal to "back to answer." Client-side navigation is what makes the live turn survive the round trip to the viewer and back.

## 0.2.31 — 2026-08-28

Non-PDF renderings and OCR text beside scans. `M1-VIEW-FE-047`.

### Added

- **Converted-text and spreadsheet renderers** (`web/components/documents/converted-text-view.tsx`, `spreadsheet-view.tsx`, `web/lib/document-format.ts`) — Word, PowerPoint, plain text, Markdown and HTML open at the cited anchor with structure preserved and the passage marked; a document with no headings lands at its chunk position with a stated note. A spreadsheet opens as a table, hand-windowed (no new dependency) to keep a many-thousand-row sheet to a few dozen live DOM rows, scrolled to and highlighting the cited row.
- **OCR-text-alongside for a scanned PDF page** (`document-viewer.tsx`) — the rendering table's "Image" row: a scanned page now shows its own OCR'd text beside the rendered page image, flagged when Askwell's confidence in it is low, and stated plainly when nothing was read at all. Standalone image files remain unsupported — no extractor reads one yet (issue #185).
- **`GET /documents/{id}/pages/{n}`** now also returns `anchor_label`, `ocr_confidence` and a server-computed `low_confidence` (against `settings.ocr_confidence_threshold`, so the browser carries no second copy of the cut line); new **`GET /documents/{id}/pages`** lists every anchor for the spreadsheet renderer's own table.

## 0.2.30 — 2026-08-28

The uncited-claim query. `M1-CITE-TEST-045`.

### Added

- **`askwell.agent.citation_check.check_citations`** (`api/src/askwell/agent/citation_check.py`) — reconciles every stored assistant answer's claims (re-segmented from `messages.content` independently of however the citation rows were written) against its `citations` rows, reporting the percentage with every claim covered and naming any answer with an uncited claim, quoting the claim's own text. An answer with no claims at all (abstention) counts as compliant. An answer with any `fact_usage` row is excluded rather than checked and counted separately — nothing populates `fact_usage` before `M3`, so a memory-backed claim cannot yet be told apart from an actually-uncited one. Runs against the already-open database session; no network call of any kind.
- **`api/tests/test_citation_check.py`** — four database-backed tests: a fully cited five-answer corpus reports 100%; deleting a citation row directly drops the figure below the bar and names that exact answer with its quoted claim; an abstention counts as compliant; a `fact_usage` row excludes rather than flags.

## 0.2.29 — 2026-08-28

The source viewer: in-app PDF at the cited page, passage highlighted. `M1-VIEW-FE-046`.

### Added

- **`GET /documents/{id}`, `GET /documents/{id}/file`, `GET /documents/{id}/pages/{n}`** (`api/src/askwell/documents.py`) — a document's metadata, its bytes (with `Range` support, so a large PDF's cited page arrives first and the rest streams behind it), and one page's own extracted text for the unrenderable fallback. Opening a document is logged to `audit_interactions` as `document_opened` — an interaction, not a decision.
- **The in-app PDF viewer** (`web/components/documents/document-viewer.tsx`, `web/app/documents/page.tsx`) — pdf.js (`pdfjs-dist`, bundled locally, no CDN), landing on the cited page with the passage highlighted for text-layer documents. The search target is the claim's own quoted span when the server found one, falling back to the full retrieved passage, falling back to a page-level highlight with a stated note when neither locates on the page — the ticket's own "the exact passage could not be pinpointed" edge case. An unrenderable page (or PDF) falls back to its extracted text plus an open-in-system-app link.
- **`web/lib/pdf-highlight.ts`, `web/lib/pdf-text-map.ts`** — the pure search-and-offset-mapping core behind the highlight, independently testable without a browser or a PDF (25 new tests).

### Changed

- **A card's click target is a query string, not a path segment**: `documentHref` (`web/lib/citations.ts`) now builds `/documents/?id=...&page=...&span=...&passage=...` rather than `/documents/{id}?page=...`, which `M1-CITE-FE-043` guessed at. A dynamic path segment cannot exist under this app's `output: "export"` — every value it will ever take must be enumerable at build time, and a document id is not. Recorded in `docs/decisions.md`, superseding the earlier guess.
- `docs/ux/source-viewer.md`'s Route line corrected to match — it named `/sources/:id?page=...&chunk=...`, which was never built and does not fit the static-export constraint either.

## 0.2.28 — 2026-08-28

Interaction records for every question and answer. `M1-ASK-OBS-041`.

### Added

- **`audit_interactions` gained the ticket's own fields**: retrieved chunk identifiers and scores, duration, backend and model — alongside the question, answer, status, source and citation count `M1-ASK-API-038` already wrote. Written in the same transaction as the assistant `messages` row and its citations, per C6 — one interaction record per question, chained and durable, or the answer does not persist.
- **A trace ring buffer write**, alongside the audited write and never gating it — `askwell.traces.TraceRing` (built by an earlier ticket, unused until now) now actually receives every turn's full step detail, failing open on a write error exactly as it always promised to.
- **`messages.trace.backend`** gained `model`, matching `docs/architecture.md` §7.1's own documented shape (`{"mode": "local", "model": "…"}`) — previously only `mode` was written.

### Fixed

- **An audit write failure now fails the turn visibly** rather than leaving it `running` forever: the transaction that would have written the answer rolls back in full (nothing unlogged persists), and a second, separate write marks the message `failed` with a stated reason so a client watching the stream sees the failure rather than a hang.

## 0.2.27 — 2026-08-28

Empty states that teach rather than say "no items". `M1-LIB-FE-051`.

### Added

- **Ask, sources present but nothing asked yet** — up to three suggested questions named from what was actually ingested, generated without a model call: a document's own chunk heading if it has one, its most frequent non-stopword term if it does not, or just its filename if it has neither (`api/src/askwell/suggestions.py`, new `GET /suggestions`). Clicking one fills the composer; it does not send.
- **Ask, sources present but none indexed yet** — an explicit "still indexing" notice in place of suggestions, rather than suggesting questions nothing can answer yet.
- **Library, empty** — names all four routes from `docs/ux/add-source.md` §1, the two shipping in Phase 1 and the two arriving in Phase 3 marked as such, replacing the placeholder copy `M1-LIB-FE-050` left in its place.
- `docs/states-and-edge-cases.md` §7's "Conversation history" row, previously unfilled: there is no separate history screen before past turns collapse (`M1-CONV-FE-178`), so the Ask screen's own empty state — suggestions or the indexing notice — stands in for it.

## 0.2.26 — 2026-08-28

The library screen renders, for the first time. `M1-LIB-FE-050`.

### Added

- **The library** (`web/components/library/library-screen.tsx`, route `/library/`) — one row per source, most recently added first: name, kind, added date, status (a word plus a distinct shape — `web/components/library/status-mark.tsx` — never colour alone, per `docs/ux/design-system.md` §8), and open clarification count (always 0 until `M3`). Filters by kind, status and has-open-clarifications, computed client-side over the same snapshot the add screen already watches.
- **Needs-attention expansion** — a source with status `attention` expands to name the specific failed or poorly-scanned document, one line per cause, with a retry action for a failure (`retryDocument`, already built by `M1-EXTRACT-VAL-030`); a flagged scan is shown as information, never as something to retry.
- **Re-index** (`POST /sources/{id}/reindex`, new) — confirms inline, stating it can take hours, before resetting every live document in a source back through extract, chunk and embed regardless of its current state. Recorded to the decisions store as `source_reindex_requested`.
- `GET /ingest`'s `sources` array gained `kind`, `added_at`, `last_error`, `open_clarifications`; its `failures` array gained `source_id` — additive fields reusing the existing snapshot rather than a new endpoint. Reasoning in `docs/decisions.md`, 2026-08-28.

## 0.2.25 — 2026-08-28

Hover pairing and the narrow-window inline fallback. `M1-CITE-FE-044`.

### Added

- **Hover and focus pairing** — hovering or focusing a cited claim raises exactly its card(s); hovering or focusing a card raises exactly its claim(s), including the two-cards-per-claim case. `web/components/ask/leader.tsx`'s store gained a `hovered` field for this — the same cross-column registry the claim/card maps already use, not a second one. The raised leader draws in `--provenance` at double weight and last, so it stays legible when leaders overlap in a dense answer.
- **`web/lib/pairing.ts`'s `isRaised`** — the pure matching rule ("this key is hovered, or paired with what is"), pulled out so it is checkable without a DOM, the same reasoning `segmentClaims` and `applyCitation` already follow.
- **The inline fallback below the three-column breakpoint** — `web/components/ask/provenance-margin.tsx`'s `InlineSourceCards` renders the live turn's cards beneath its answer (`ask-screen.tsx`'s `Turn`), CSS-shown only below `@5xl`, mirroring the margin `<aside>`'s own `hidden @5xl:block`. No card is ever removed at any width. Its left edge is `--rule-strong`, not the margin card's decorative `--provenance` — below the breakpoint there is no leader, so the edge itself carries the claim-to-source relationship.
- Keyboard focus parity: a claim span is now `tabIndex={0}` and fires the same hover/raise handlers on `focus`/`blur` that the mouse path fires on `mouseEnter`/`mouseLeave`.

### Changed

- `docs/ux/design-system.md` §7's claim-leader description corrected — it still said `--rule` at rest, left over from before `M1-CITE-FE-043` moved the leader to `--rule-strong`.

## 0.2.24 — 2026-08-28

The provenance margin renders, for the first time. `M1-CITE-FE-043`.

### Added

- **The provenance margin** (`web/components/ask/provenance-margin.tsx`) — one card per cited passage, filename, page or anchor, and the exact retrieved passage, entering the margin as claims are cited during streaming rather than waiting for the answer to finish. Replaces `Shell`'s static placeholder text with a live view of `AskProvider`'s own turn state.
- **`lib/citations.ts`'s `applyCitation`** — groups `citation` events by `chunk_id` rather than by event, so two claims citing the same passage produce one card carrying two claim ordinals, not a duplicate card.
- **A hairline leader** (`web/components/ask/leader.tsx`) joining each claim's rendered text to its card, drawn in `--rule-strong`. A registry, not a prop, because the claim (centre column) and the card (margin rail) are DOM siblings under `ShellFrame`; a short poll keeps it tracking reflow while a turn streams, and falls back to resize/scroll recompute once it settles.
- **`lib/claims.ts`'s `segmentClaims`** — a client-side mirror of `askwell.agent.claims.segment_claims`, run against the same growing answer text so the two sides agree on claim ordinals without either telling the other.
- **The `citation` SSE event now carries `filename`, `anchor_kind`, `heading` and `passage`** (`api/src/askwell/ask.py`, `askwell.retrieve.Candidate`) — the citations table is unchanged; this is display data the browser had no route to before, joined in from `documents` alongside the chunk already being fetched.

### Changed

- `web/lib/ask.ts`'s `AskTurnState`/`applyAskEvent` no longer track a citation count — `AskTurn.citations: CitationCard[]` (`ask-state.tsx`) is the real data the margin renders, kept in its own module rather than folded into `applyAskEvent`.

### Known gaps

- **Click-through has no landing yet.** The card links to `/documents/{id}?page=N`, a route `M1-VIEW-FE-048` has not built — the click is wired to where the viewer will live, per this ticket's own Out of Scope line, and 404s until then.
- **No hover pairing or narrow-window fallback** (`M1-CITE-FE-044`) — the leader is always visible, not raised on hover, and the margin is hidden below the three-column breakpoint rather than reflowing inline (unchanged from `Shell`'s existing behaviour, since that reflow is that ticket's own scope).
- **Deleted-source rendering waits for deletion to exist** (`M2`) — nothing here renders a moved or deleted document differently; a card for either still renders normally.
- **Not exercised against a real model or a real browser** in this environment — verified by `scripts/dev.sh test`, `test-db` (`api/tests/test_ask_api.py`'s wire-format assertions now include the new citation fields) and `scripts/dev.sh web-check` (typecheck, lint, the new `lib/claims.test.ts`/`lib/citations.test.ts`, build, contrast, offline-check), the same limits `M1-ASK-BE-040`/`M1-CITE-BE-042` already recorded.

## 0.2.23 — 2026-08-28

Claim-level citations, as data rather than as prose. `M1-CITE-BE-042`.

### Added

- **`askwell.agent.claims.segment_claims`** — reads the model's own answer text as sentences, each one a claim only if it carries a citation marker `[index]` immediately before its closing punctuation. A sentence with no marker (a restatement of the question, a transition) is not a claim, and is never counted as an uncited one.
- **`askwell.agent.claims.locate_quoted_span`** — the claim's own words, if they occur verbatim (case-insensitive) in the source chunk; `None`, never a dropped citation, when they do not.
- **`citations.quoted_span` is written for the first time** — left `null` since `M1-ASK-API-038`. A claim citing two passages now produces two citation rows sharing one `claim_ordinal`, rather than one row per unique index across the whole answer.
- **The `citation` SSE event carries `claim_ordinal` and `quoted_span`** alongside the chunk it already named, so a card can render per claim as it is emitted rather than only once at the end.

### Changed

- `answer_composition.v1.md`'s Citing section now states the convention `segment_claims` reads back: one factual claim per sentence, markers immediately before the sentence's own closing punctuation, no marker at all on a sentence that asserts nothing from the retrieved content.

## 0.2.22 — 2026-08-28

Generation continues server-side when the user navigates away, made a fully closed loop. `M1-ASK-BE-040`.

### Added

- **The assistant `messages` row is written `running` before generation starts**, not after it finishes — `POST /ask` inserts it in the same request that starts the background task. A message can no longer exist only in memory: the row `reconcile_interrupted` needs to find is there from the first instant.
- **`askwell.ask.reconcile_interrupted`**, run once at startup (`api/src/askwell/app.py`, gated on Postgres being reachable) — fails every assistant row still `running`, which can only mean the previous process died mid-answer. The stated edge case: the stack restarts mid-generation, the answer is lost, and the message is marked failed rather than left pending forever.
- **`Settings.generation_max_concurrent`** (default 2, `ASKWELL_GENERATION_MAX_CONCURRENT`) bounds how many turns retrieve-and-generate at once. Several abandoned questions queue behind the limit rather than each starting a full inference pass immediately — the same reasoning `ingest_concurrency` already applies to ingestion.
- **`GET /ask/counts`** gained `abandoned` — turns `reconcile_interrupted` failed on the machine's behalf, kept separate from an ordinary inference failure. C1: read from this machine's own `messages` rows, nothing transmitted.

## 0.2.21 — 2026-08-28

The mic control, reserved and disabled. `M1-ASK-FE-039a`.

### Added

- **Mic control in the composer** (`web/components/ask/ask-screen.tsx`) — present beside "Ask" from Phase 1, at its final position and size (`docs/ux/voice.md` §2), so M6 enables it in place rather than reflowing the composer around it. Disabled with `aria-disabled` rather than the `disabled` attribute, so it stays reachable by keyboard and a screen reader announces it as disabled with its reason — a tooltip on hover and on focus — instead of an unlabelled dead stop. No audio work of any kind: no microphone permission is requested, clicking it does nothing.

## 0.2.20 — 2026-08-28

The Ask screen, for the first time. `M1-ASK-FE-039`.

### Added

- **The Ask screen** (`web/components/ask/ask-screen.tsx`) — the composer (`Enter` submits, `Shift+Enter` newlines), named step labels ahead of the first token, and tokens streamed into the live turn as `POST /ask` (`M1-ASK-API-038`) produces them.
- **`AskProvider`** (`web/components/ask/ask-state.tsx`) — the conversation held once above the router, matching `AddProvider`'s own reasoning, so a completed answer survives navigating away and back. A question asked while one is running is queued, not interleaved — one answer at a time, nothing silently dropped.
- **`⌘K` / `Ctrl+K`** reaches the Ask screen and focuses the composer from anywhere in the shell.
- **`web/lib/ask.ts`** — the SSE parser and `streamAsk`/`stopAsk` client for `POST /ask`, `POST /ask/{message_id}/stop`.
- A non-Latin-script question gets Askwell's English-only statement instead of a poor answer — a heuristic, not language detection; documented as such (`web/lib/ask.ts`).

### Known gap

- **`conversation_id` is not threaded across turns.** `askwell.ask` never returns the id it resolved or created, so every question opens its own conversation server-side. Filed as issue [#156](https://github.com/Rumeasiyan/askwell/issues/156) rather than worked around; does not affect this ticket's own acceptance criteria.

## 0.2.19 — 2026-08-28

A question gets an answer, over the wire, for the first time. `M1-ASK-API-038`.

### Added

- **`POST /ask`** — starts a turn: resolves or opens a conversation, records the user's question, and returns a server-sent stream over the same background generation a browser can drop and reconnect to. Runs retrieval (`M1-ASK-RET-035`/`036`) and composition (`M1-ASK-BE-037`) for the first time against a real question, then streams the model's own tokens as `InferenceClient.stream_generate` produces them (new — see below).
- **`GET /ask/{message_id}/stream`** — reconnects to a turn still running, or replays a finished one from `messages` once it has left memory (a retired turn, or this process having restarted). A turn's own event history is small enough to replay in full rather than tracking what a given browser has already seen; `docs/decisions.md` records why this departs from the ticket's stated "does not replay tokens already sent" and what the alternative design's bug was.
- **`POST /ask/{message_id}/stop`** — ends generation early; the stored answer is marked partial (`messages.trace.stopped_early`).
- **`askwell.inference.client.InferenceClient.stream_generate`** — generation as an async stream of `StreamChunk`s over llama.cpp's own SSE `/completion` response, instead of `generate`'s one round trip. Raises the same `InferenceUnavailable`/`InferenceFailed` distinction as every other method, wherever in the stream the failure happens — including after tokens have already been sent, the "inference process dies mid-stream" edge case.
- **Citations, for the first time.** The model is asked to cite by the same `index` `compose()` delimits candidates with; `askwell.ask` resolves `[index]` references out of the streamed text as they complete and writes them to the real `citations` table (`docs/architecture.md` §7) — C4 having somewhere to attach to, not just `messages.trace`.
- **`ASKWELL_GENERATION_MAX_TOKENS`** (default 1024) — the ceiling on one answer's length. Reaching it is stated (`trace.reason`), never silent.
- **`api/tests/conftest.py::drive_and_disconnect`** — the raw-ASGI streaming-test helper issue #110 predicted this ticket would need, extracted so a third streaming endpoint does not rediscover the pattern `test_ingest_api.py` found the hard way.

### Verified

- `scripts/dev.sh test` — 425 passed, 1 skipped (unchanged, pre-existing).
- `scripts/dev.sh test-db` — 161 passed, including the full acceptance-criteria exchange (steps before tokens, a citation resolved to its chunk, stop marking an answer partial, a disconnected browser's answer still completing and saving) driven against a real Postgres with a stubbed `InferenceClient`.
- Manual walkthrough against the running stack (`docs/manual-tests/M1-ASK-API-038.md`): a real session, `POST /ask` streaming a `step` event before failing cleanly on `InferenceUnavailable` (no native `llama.cpp` process runs in this environment — the same limitation every ticket since `M0-MODEL-BE-019` has recorded), the assistant/user messages and the audit interaction row all present afterward, `GET /ask/{id}/stream` replaying correctly both while the process was still up and after `podman compose restart api` cleared the in-memory turn registry, and both stream/stop endpoints answering 404 by name for an unknown id.

### Not demonstrable yet, stated plainly

No real model ran: every test and the manual walkthrough stub or fail at `InferenceClient`, so token pacing, citation accuracy against a real model's own output, and whether a real generation actually honours the `<retrieved-content>` boundary are unverified here — the same gap every ticket since `M0-MODEL-BE-019` has recorded. The Ask screen itself does not exist (`M1-ASK-FE-039`), so nothing renders any of this yet. Abstention is still `M2`: this ticket answers from zero or thin candidates rather than refusing, which is correct for its own scope and wrong for a shipped product — `M2` is what makes that a decision instead of an omission.

- **`GET /ask/counts`** — answers started, completed and stopped on this machine, the ticket's Analytics Events line. Derived from `messages` rather than counted in memory, so they survive a restart: a counter held in the process would reset with the container and report "since the last deploy" under a name that reads like a total. Read out of this machine's own database by this machine's own browser; nothing transmitted, no collector to turn off (C1).

## 0.2.18 — 2026-08-28

A document cannot give Askwell orders. `M1-ASK-BE-037`.

### Added

- **`api/src/askwell/agent/prompts/answer_composition.v1.md`** — the first versioned prompt file, and the first prompt text of any kind in the repository: no system prompt string lives in application logic. States, as a standing statement, that text inside a `<retrieved-content>` block is data extracted from the user's own files and never an instruction, however it reads.
- **`askwell.agent.compose.compose`** — wraps every retrieved candidate in a `<retrieved-content index="…" chunk_id="…">` block before the question, so delimitation holds regardless of candidate count or passage length, and scans each candidate's content against a small, named-as-heuristic set of instruction-like patterns (`_INSTRUCTION_PATTERNS`). A match sets `ComposedPrompt.injection_flagged` and lists the matched patterns — the composed prompt itself is unaffected either way, matching the ticket's own "flagged, not blocking" requirement. `ComposedPrompt.prompt_version` carries `answer_composition.v1` on every call.

### Verified

- `api/tests/test_compose.py`: the prompt file exists, is versioned, and both C7 mechanisms — the standing statement and the delimiter — are present, with two tests that fail if either is stripped from the file (a stand-in for the real file, since the real one obviously still has both). Delimitation survives twenty candidates of long passages. Ordinary content is not flagged; an "ignore all previous instructions … reveal your system prompt" passage is flagged, with the composed system prompt byte-identical to the unflagged case and the injected text still present verbatim (data, not obeyed, not stripped). Policy-manual-style instructional prose is flagged but composes normally, per the ticket's own edge case. Empty candidates compose without error.
- `scripts/dev.sh check` — 425 passed (up from 414), 1 skipped (unrelated, pre-existing), lint/format/`mypy --strict` clean over 52 modules.

### Not demonstrable yet, stated plainly

No `ask` endpoint exists (`M1-ASK-API-038`, next), so nothing calls `compose()` against a real question and real retrieved candidates end to end, and `ComposedPrompt.injection_flagged`/`.prompt_version` are captured but written nowhere — `messages.trace.injection_flagged` (`docs/architecture.md` §7.1) has no writer until that ticket exists. This matches exactly how `M1-ASK-RET-035`/`036` left their own new fields captured and unread until a consumer existed.

The passage that actually answers the question is the one at the top, not just among the fused candidates. `M1-ASK-RET-036`.

### Added

- **A reranking pass in `askwell.retrieve.retrieve`.** After fusion, the top `Settings.rerank_candidate_count` candidates (default 10, bounded separately from `retrieval_candidate_count` to keep latency inside budget) are scored by `InferenceClient.rerank` — the cross-encoder pass already built and unused since `M0-MODEL-BE-019`/`M1-ASK-RET-035`. `Candidate.rerank_score` retains the raw cross-encoder score alongside the fused, dense and lexical scores already there, never mixed with them. Candidates beyond the window are appended unreordered rather than padded or dropped.
- **`RetrievalResult.reranked`, `.rerank_duration_ms` and `.rerank_skipped_reason`.** If the reranker is unavailable or fails or times out, `retrieve()` returns fusion order unchanged and `reranked = False` with a reason — an answer still comes back rather than the request failing.
- Two new settings: `ASKWELL_RERANK_CANDIDATE_COUNT` (default 10) and `ASKWELL_RERANK_TIMEOUT_SECONDS` (default 10.0).

### Verified

- `api/tests/test_rerank.py`: `_rerank` in isolation against a real Unix socket stub — reordering happens and both scores are retained; fewer candidates than the window needs no padding; candidates beyond the window are appended unreordered; an unavailable or failing reranker degrades to fusion order with a stated reason; no candidates skips reranking without asking the assistant; tied scores keep a stable order.
- `api/tests/test_retrieve_records.py`, against real Postgres: on five chunks scoring identically under fusion, the right supplier's passage is promoted to the top by reranking; with the reranker unavailable, `retrieve()` still returns the fusion-ordered result.
- On the running stack, rebuilt to `0.2.17`, against real Postgres: a fake client promoting the Meridian passage produced `reranked=True` with the right passage first and both score sets populated; the real `InferenceClient.rerank` against the actual absent inference socket in this environment produced `reranked=False`, `rerank_skipped_reason='reranker unavailable: The assistant is stopped.'`, and the fusion-ordered candidate still came back. A live walkthrough with a real reranker model actually scoring was not run — no native `llama.cpp` process is available in this environment, the same limitation every ticket since `M0-MODEL-BE-019` has recorded.

## 0.2.17 — 2026-08-28

The passage that actually answers the question is the one at the top, not just among the fused candidates. `M1-ASK-RET-036`.

### Added

- **A reranking pass in `askwell.retrieve.retrieve`.** After fusion, the top `Settings.rerank_candidate_count` candidates (default 10, bounded separately from `retrieval_candidate_count` to keep latency inside budget) are scored by `InferenceClient.rerank` — the cross-encoder pass already built and unused since `M0-MODEL-BE-019`/`M1-ASK-RET-035`. `Candidate.rerank_score` retains the raw cross-encoder score alongside the fused, dense and lexical scores already there, never mixed with them. Candidates beyond the window are appended unreordered rather than padded or dropped.
- **`RetrievalResult.reranked`, `.rerank_duration_ms` and `.rerank_skipped_reason`.** If the reranker is unavailable or fails or times out, `retrieve()` returns fusion order unchanged and `reranked = False` with a reason — an answer still comes back rather than the request failing.
- Two new settings: `ASKWELL_RERANK_CANDIDATE_COUNT` (default 10) and `ASKWELL_RERANK_TIMEOUT_SECONDS` (default 10.0).

### Verified

- `api/tests/test_rerank.py`: `_rerank` in isolation against a real Unix socket stub — reordering happens and both scores are retained; fewer candidates than the window needs no padding; candidates beyond the window are appended unreordered; an unavailable or failing reranker degrades to fusion order with a stated reason; no candidates skips reranking without asking the assistant; tied scores keep a stable order.
- `api/tests/test_retrieve_records.py`, against real Postgres: on five chunks scoring identically under fusion, the right supplier's passage is promoted to the top by reranking; with the reranker unavailable, `retrieve()` still returns the fusion-ordered result.
- On the running stack, rebuilt to `0.2.17`, against real Postgres: a fake client promoting the Meridian passage produced `reranked=True` with the right passage first and both score sets populated; the real `InferenceClient.rerank` against the actual absent inference socket in this environment produced `reranked=False`, `rerank_skipped_reason='reranker unavailable: The assistant is stopped.'`, and the fusion-ordered candidate still came back. A live walkthrough with a real reranker model actually scoring was not run — no native `llama.cpp` process is available in this environment, the same limitation every ticket since `M0-MODEL-BE-019` has recorded.

## 0.2.16 — 2026-08-28

A question mixing a name and a concept returns candidates found by either. `M1-ASK-RET-035`.

### Added

- **`askwell.retrieve.retrieve`** — dense search (pgvector cosine, `chunks.embedding`) and lexical search (`chunks.content_tsv`, hyphen-normalised query text to match `c7e2f814a5b3`'s own tokenising) run independently, each bounded to `Settings.retrieval_candidate_count`, and are fused with Reciprocal Rank Fusion (`RRF_K = 60`). Every candidate retains its own dense score, lexical score (either nullable, if only one search found it) and the fused score it was ranked by — nothing is recomputed from the fused list alone. `Settings.retrieval_score_threshold` is captured on the result as configured at call time, for the trace to show a near-miss later, without applying it — abstaining on it is `M2`.
- **`source_id` scopes both searches to one source.** Both queries exclude superseded (`superseded_by IS NOT NULL`) and deleted (`deleted_at IS NOT NULL`) documents at the query itself.
- Two new settings: `ASKWELL_RETRIEVAL_CANDIDATE_COUNT` (default 40) and `ASKWELL_RETRIEVAL_SCORE_THRESHOLD` (default 0.65, matching `docs/architecture.md` §7.1's own example).

### Verified

- `api/tests/test_retrieve.py`: `_fuse` in isolation — a hit in both lists outranks a hit in only one, a missing side keeps a null score, the fused score is the reciprocal-rank sum, no hits returns nothing, identical content from two documents is never deduplicated, the result is truncated to the candidate count.
- `api/tests/test_retrieve_records.py`, against real Postgres: a reference number (`INV-2024-0917`) retrieves the chunk that contains it by lexical search alone; a paraphrase with no shared wording retrieves the right chunk by dense search alone; scores and threshold land on the result as configured; a superseded document and a deleted document are both excluded while the live one is returned; an empty corpus returns cleanly; a one-word query does not error; a one-document corpus still fuses; identical content in two documents returns both; scoping to a source excludes a matching chunk in another source.
- `scripts/dev.sh check` — 407 passed, 1 skipped. `scripts/dev.sh test-db` — 150 passed, up from 141, 10 of them new.

### Deferred

- No caller exists yet — nothing in the repository invokes `retrieve()`. The `ask` endpoint, streaming, and writing `messages.trace` are `M1-ASK-RET-036` (reranking) and later M1/M2 tickets; this ticket's own scope is the two searches and their fusion, not the surface that calls them.
- No vector index (`ivfflat`/`hnsw`) on `chunks.embedding` — both searches are sequential scans. Not needed yet at the corpus sizes this milestone targets; worth revisiting once a real corpus makes `_dense_search` measurably slow.

## 0.2.15 — 2026-08-28

Re-adding a changed document offers to replace the old version rather than duplicating it. `M1-INDEX-BE-034`.

### Added

- **A file at an already-indexed path with different content is offered as a new version, not silently duplicated or silently inserted.** `POST /sources` gains `version_decisions`, a map from relative path to `"supersede"` or `"keep_both"`; a path with no entry that turns out to be a changed revision comes back as `new_version` with nothing recorded, so declining costs nothing to reverse. `"supersede"` retires the old document (`documents.superseded_by`) and records the new one at `version + 1` in the same transaction — never both or neither. `"keep_both"` inserts the new file as an ordinary independent document; the schema's own uniqueness (`uq_documents_live_source_id_sha256`) is keyed on content, not path, so two live documents at one path was already a state it permitted.
- **A decisions-store record naming both versions**, `document_superseded`, alongside the ordinary `document_added` for the new row — so a later audit read can answer "what replaced what" without inferring it from two independent rows.

### Verified

- `api/tests/test_sources_records.py`: a changed file at the same path is offered, not duplicated, and nothing is recorded until decided; accepting sets `superseded_by` and bumps `version` without touching `deleted_at`; declining leaves both live; superseding a document that is itself already-superseded chains through the current live tip rather than orphaning; a new path with identical content is still recognised as a plain duplicate before the path-based version check ever runs.
- `scripts/dev.sh check` — 401 passed, 1 skipped (unmarked suite; supersession tests are `requires_db`). `scripts/dev.sh test-db` — 141 passed, up from 136, all 5 new tests among them.
- On the running stack (`ASKWELL_ROOTS_MOUNT` set to a temporary directory for the session): added a `.txt` file, edited it on disk, re-added it and received `new_version` with nothing changed in the database; re-added with `version_decisions: {"file.txt": "supersede"}` and confirmed via `psql` that the old row's `superseded_by` now points at the new row, the new row is `version` 2, and the old row's `deleted_at` is still null.

### Deferred

- The superseded banner the source viewer would render (`docs/ux/source-viewer.md` §4) has nowhere to attach yet — no document-detail or citation-resolution endpoint exists in the repository. Filed as [#141](https://github.com/Rumeasiyan/askwell/issues/141), owned by whichever ticket builds that surface.
- Retrieval excluding superseded versions is not yet exercisable — no retrieval component exists (`M1-ASK-RET-035`/`036`). The requirement is recorded in `docs/decisions.md` so the retrieval ticket filters `superseded_by IS NULL` rather than rediscovering the need.

## 0.2.14 — 2026-08-28

A reference number is findable by the part someone actually remembers. `M1-INDEX-DB-033`.

### Fixed

- **`content_tsv` no longer buries a reference number's sign inside its own lexeme.** Postgres's default parser reads a hyphen before a digit run as a minus sign, so `INV-2024-0917` tokenised as `inv`, `-2024`, `-0917` — a search for just `0917` never matched. `chunks.content_tsv`'s generated-column expression now replaces hyphens with spaces before tokenising, so each group indexes independently and matches alone. Migration `c7e2f814a5b3`; reasoning in `docs/decisions.md`.

### Verified

- The column and its GIN index (`ix_chunks_content_tsv`) already existed and already auto-populated on every write (`a8208099ef38`) — nothing new to build there. `api/tests/test_index_db_records.py` proves: every written chunk gets a populated value; a chunk with no content gets an empty, non-null vector rather than dropping out of the index; a reference number matches both in full and by its trailing group; a pure-numeric or very long chunk indexes without error; re-chunking a document leaves exactly one row, not two; and, seeded to 300,000 chunks, a lexical query's `EXPLAIN` plan uses `ix_chunks_content_tsv` rather than a sequential scan.

## 0.2.13 — 2026-08-28

Chunks are actually embedded — the last stage of the ingestion pipeline, and the first thing that makes anything searchable. `M1-INDEX-ING-032`.

### Added

- **An `embed` stage, real for the first time.** `api/src/askwell/embed.py` sends every un-embedded chunk of a document to the native inference process in bounded batches (`ASKWELL_EMBEDDING_BATCH_SIZE`, default 16), retrying a failing batch with backoff before giving up on the document. Wired into `ingest.STAGES`; a document now reaches `ready` only once every one of its chunks has an embedding — never partially.
- **A batch failure retries; exhaustion is visible and retryable.** A transient inference blip (the process restarting mid-batch, a slow request) retries up to three times with a short linear backoff inside this stage; if that is exhausted, the whole document fails through the pipeline's existing per-document retry and failure surface (`GET /ingest`, `POST /ingest/documents/{id}/retry`) — nothing is silently dropped.
- **The embedding dimension is checked once, at worker startup.** `askwell.worker.startup` refuses to start — rather than failing one opaque batch at a time — if `ASKWELL_EMBEDDING_DIMENSIONS` does not match the width `chunks.embedding` was actually migrated at.
- **An empty chunk is refused as a second line of defence.** `askwell.chunk` already guarantees this cannot happen; `embed` checks anyway, so a defect upstream surfaces as a named failure rather than a citation pointing at nothing.

## 0.2.12 — 2026-08-28

Chunking respects structure instead of cutting at a fixed length. `M1-INDEX-ING-031`.

### Added

- **A `chunk` stage, real for the first time.** `api/src/askwell/chunk.py` parses `document_pages.text` back into the headings, `[TABLE]`/`[/TABLE]` markers and list items the extractors already left in it, merges them into `chunks` rows up to a target size without ever crossing a hard maximum, and writes `document_id`, `ordinal`, `page_from`/`page_to`, `heading` and `content` — `embedding` stays null for `M1-INDEX-ING-032`. Wired into `ingest.STAGES`; a document now parks at `embed` instead of `chunk`.
- **A table is never split from its header.** A table longer than the hard maximum is split by row with the header repeated on every part; a heading is carried as every following chunk's `heading` column until the next one; a single paragraph longer than the maximum splits at sentence boundaries with overlap so a sentence is never orphaned; a slide (`documents.anchor_kind = 'slide'`) is never merged with another slide into one chunk.

## 0.2.11 — 2026-08-28

Extraction failures are named individually, and a password-protected PDF prompts rather than just failing. `M1-EXTRACT-VAL-030`.

### Added

- **Extraction failures classified by cause**: a file missing from disk (`MissingSource`), unreadable due to permissions (`UnreadableSource`), corrupt (`CorruptDocument`), or password-protected (`PasswordProtected`/`WrongPassword`) each carry their own reason naming the file, instead of a raw library exception surfacing as the message. `MissingSource`/`UnreadableSource` are checked once, ahead of every format's own parser, so a file that vanished between add and extraction reads distinctly from one that opened and turned out broken.
- **A password-protected PDF prompts for its password.** `POST /ingest/documents/{id}/password` retries a failed document with a password for that one attempt — never written to a database row or a log line, since storage needs the credential encryption path M4 adds and is not offered until then. A wrong password is reported as wrong and the file stays listed as failed, not dropped; the right one completes ingestion.

## 0.2.10 — 2026-08-28

Low-confidence OCR is flagged rather than silently indexed. `M1-EXTRACT-ING-029`.

### Added

- **OCR confidence, measured and stored.** Every OCR'd page's Tesseract confidence is kept (`document_pages.ocr_confidence`), and `documents.ocr_confidence` is their mean. A text-layer page or document carries no confidence at all — nothing to be false about, since Tesseract was never asked.
- **A source shows `needs attention` for poor OCR, with a specific reason.** Below `ASKWELL_OCR_CONFIDENCE_THRESHOLD` (default `0.60`, configuration), a document is flagged — never a failure, and never removed from the index. A mixed document names the specific pages that read worst. The `/ingest` snapshot carries a `flagged` list and a local `documents_flagged` counter (C1: nothing transmitted).

### Changed

- **`sources.last_error` now names both causes when both are true** — failed files and flagged files in the same sentence, rather than one overwriting the other.

## 0.2.9 — 2026-08-28

A scanned PDF with no text layer is now actually read. `M1-EXTRACT-ING-028`.

### Added

- **OCR fallback with orientation detection.** A page whose text layer fails extraction's usability check is rendered to an image and read by Tesseract — orientation and script detected first, so an upside-down or sideways scan still reads correctly. Runs per page, so a mixed document only pays the OCR cost on the pages that actually need it.
- **`documents.ocr_derived`**, so the source viewer can later show the scanned image beside the text for a document that used OCR.
- **Tamil OCR as the same hedge everywhere else in the product**: the bundled `tam` traineddata recognises Tamil script when Tesseract's own script detection identifies it, but the language is never presented as supported.

### Changed

- **A PDF that never gets any text — not from a text layer, not from OCR — now fails with a reason**, the same C5 failure every other extractor already reports, instead of parking forever awaiting a ticket that has now landed.

## 0.2.8 — 2026-08-28

Word, PowerPoint, spreadsheet, plain text, Markdown and HTML now extract for real. `M1-EXTRACT-ING-027`.

### Added

- **`.docx`, `.pptx` and `.xlsx` extraction**, via `python-docx`, `python-pptx` and `openpyxl` — all MIT-licensed. Headings, list items and table boundaries survive as structural markers; a slide's speaker notes are included and labelled; a spreadsheet is read document-style, one row per anchor, across every sheet.
- **Plain text, Markdown and HTML extraction**, sectioned by heading where one exists. A Markdown file's YAML front matter is excluded from the indexed prose. An HTML page has its navigation chrome and `<title>` discarded, keeping only what a reader actually sees.
- **`documents.anchor_kind` and `document_pages.anchor_label`**, so the source viewer knows what a document's page-equivalent ordinal means — a PDF page, a slide, a spreadsheet row, or a heading — and can render the right pointer next to it.
- **A document with nothing extractable in it fails with a reason**, never reaching `ready` empty — the same C5 failure a PDF with no text layer already produces, for every new format.
- **A legacy binary Office file (`.doc`, `.xls`, `.ppt`) fails by name**, retryable, rather than crashing unreadably or being silently skipped — a known gap, tracked as issue #121.

## 0.2.7 — 2026-08-28

The ingestion pipeline's first real stage. `M1-EXTRACT-ING-026`.

### Added

- **PDF text-layer extraction, page by page.** `pypdfium2` reads each page of a digital PDF and records its text with a page number that matches what a person sees at the bottom of the printed page. `documents.page_count` is set from the real page count, not a guess.
- **`document_pages`, one row per page whether or not it has text.** A blank page is recorded rather than skipped, so the OCR ticket (`M1-EXTRACT-ING-028`) can find exactly the pages it owns without extraction having decided anything on its behalf.
- **A PDF with no usable text layer anywhere parks naming `M1-EXTRACT-ING-028`**, the same way a document waiting on chunking parks naming that ticket — not indexed empty, not failed. A document with a text layer on some pages and not others is not this case: it proceeds, with its blank pages on record.
- **A document parked before this version is revived, not stranded.** Anything added before this ticket landed was sitting `parked` waiting for `extract`; the worker now returns those to the queue at startup instead of leaving them parked forever. Issue [#109](https://github.com/Rumeasiyan/askwell/issues/109).

### Changed

- A pipeline stage now receives a database session of its own, not only the file and a progress callback — the shape every real stage needs, `extract` being the first to use it.

## 0.2.6 — 2026-08-28

Indexing stops belonging to the page you are looking at. `M1-ADD-ING-025`.

Three defects the audit found before this shipped are fixed here rather than filed for later: the browser opened one event stream per drop and stalled the tab after six, a failed file reached the screen as a bare count, and a queue that had lost a worker could not restart itself for an hour.

### Added

- **Ingestion is a background job.** Recording a drop now writes a queue row per document in the same transaction as the document itself, and a worker picks them up. The add request ends; the work does not. Navigating away, closing the tab and restarting the browser leave the import running.
- **A durable queue, not just a Redis one.** `ingest_jobs` is the record and Redis is the transport. A worker killed mid-job has its work returned to the queue at startup; a Redis that was flushed, unreachable, or asleep with the laptop is repaired by a reconcile that runs every half minute. Nothing that was committed is lost by the queue being unavailable — it is delayed.
- **Progress per file and inside a file.** `GET /ingest` is a snapshot and `GET /ingest/stream` is the same payload as server-sent events, pushed only when something changes. Both carry the running count, each queued file's position, and the bytes done and total for whatever is being read — so one 900-page scan shows movement rather than an untimed spinner.
- **An estimate that says what it is based on, or refuses to give one.** Before anything has finished indexing on this machine there is no throughput history, so the answer is no number and a sentence saying why. A measured estimate carries the count and average it was extrapolated from.
- **Partial coverage, so a source is askable early.** Every source reports how many of its documents are indexed and whether it can be asked about at all. Eighty of five hundred papers is eighty papers' worth of answers, not a wait.
- **A failed document is visible with its reason and a retry.** Three attempts, then it rests as failed with the error stored where the library can render it — in Postgres, so it survives the queue. `POST /ingest/documents/{id}/retry` forgives the attempts and puts it back.
- **Concurrency is configuration and defaults to two.** `ASKWELL_INGEST_CONCURRENCY`, because this laptop is also running the user's browser. `ASKWELL_INGEST_JOB_TIMEOUT_SECONDS` defaults to an hour: OCR over a long scan is genuinely that slow, and the queue's five-minute default would call a slow file a failed one.
- Documents recorded before this version — by `M1-ADD-BE-023`, when there was no queue — are enqueued by the migration. They would otherwise have waited forever for a worker that had nothing to tell it they existed.

### Changed

- The add screen's *Queued* panel is live. It says what the queue is doing, what position a file is in, and — while the pipeline is incomplete — what has to arrive before anything is searchable, instead of promising that background ingestion is coming.
- A source's status is derived from its documents rather than set by hand, and a change is a decisions record naming what moved and how much of the source was ready at the time.

### Known gaps

- **Nothing is extracted, chunked or embedded yet, so no document reaches `ready` on its own.** Those three stages are declared in the pipeline, named with their tickets, and not built: `M1-EXTRACT-ING-026`, `M1-INDEX-ING-031`, `M1-INDEX-ING-032`. A job runs, reaches extraction, finds nothing installed and parks there saying so. The queue, the progress, the failure handling and the resume are real and are exercised by tests that install a stage of their own; what a fresh install sees today is an honest "recorded and waiting", not a progress bar.
- Documents already parked when a stage is later installed are not automatically re-queued. Issue [#109](https://github.com/Rumeasiyan/askwell/issues/109).
- Hashing still happens inside the add request. The queue that would move it now exists — issue [#105](https://github.com/Rumeasiyan/askwell/issues/105).
- Disk budget refusal is not implemented. M7.

## 0.2.5 — 2026-08-28

Askwell remembers what it was given, and notices when it has been given it before. `M1-ADD-BE-023`.

### Added

- **A queued batch becomes records.** `POST /sources` creates one source for the folder and one document per file, carrying the path, the filename, the media type, a SHA-256 of the contents and when it arrived. The add screen no longer ends at a sentence about work that has not started — it ends at rows.
- **The same file is recognised rather than indexed twice.** By content hash, across every source: `contract.pdf` and `contract copy.pdf` in one drop, or the same PDF added later from a different folder, are recognised and linked to the document that already holds those bytes. Both paths are shown, so it is clear which copy Askwell is reading. Duplicate passages in retrieval are what make a citation ambiguous, which is the cost this avoids.
- The partial unique index that enforces one live version per source and hash — which has existed in every database since the first migration and in no model — is now **declared in the model**, so it stops being an invariant an autogenerated migration would propose dropping.
- **`queued` is a status of its own**, for both sources and documents, and it is the default. A row that has been recorded and is waiting is not a row being read, and storing it as `indexing` is what a progress bar that never moves is rendered from.
- **The server decides what a file is, from its own read of the bytes.** Detection also runs in the browser and always did; that answer is what the user watches during a drop and is now explicitly a courtesy rather than a boundary. Nothing the client says about a file's type is stored.
- **Adding is a decisions record.** One for the source and one per document, each naming the path — carried forward from `M1-ADD-FE-022`, which stated the requirement and could not meet it from a screen. A refusal and a duplicate are logged instead: nothing changed, and the decisions store is kept forever.
- **Refusals now reach the operational log**, which is the durable record the browser's local counter was not. Carried forward from `M1-ADD-VAL-024`.

### Changed

- The local "files added" counter follows what the server actually added, not what the screen sent. Re-adding a folder no longer inflates it.

### Known gaps

- Nothing extracts, embeds or indexes these documents yet — that is `M1-ADD-ING-025`. The status transitions past `queued` belong to the ingester and are not exercised here.
- A changed version of a file already indexed is recorded as a new document rather than as a supersession. `M1-INDEX-BE-034`.
- Hashing happens inside the request. For a large drop of large files that is a long request, and there is no progress while it runs.

## 0.2.4 — 2026-08-27

An unsupported file is refused by name, and a CSV is told when its turn comes. `M1-ADD-VAL-024`.

### Added

- **Markdown and HTML are read.** `docs/data-sources.md` §1 has listed both since it was written and detection had neither: an HTML page is recognised by its opening rather than its name — before this a saved page full of tables was read as a CSV — and Markdown is named from its extension, which is the one place the name is better evidence than the bytes.
- **A refusal names the file, what its contents turned out to be, and what would work.** Per file, with the supported list once beneath the block rather than repeated after each of five.
- **A drop that expands to no files says so** — an empty folder, nothing changed. A cancelled file dialog still says nothing.
- A local counter of files turned away, beside the one for files added. Same store, same absence of a wire (C1).

### Changed

- **A CSV or a dump is named as *arriving*, not as unsupported, and is no longer queued.** Detection now answers three ways — indexed today, arriving in a later milestone, refused — where it answered two. The screen previously said "Arrives in M4" in one panel while queueing a CSV as though it worked in another; the file's own route is what decides, read from the same table the panel is rendered from, so M4 flips both at once.
- Rejection is per file throughout: one archive among sixty contracts refuses the archive and queues the contracts.

### Known gaps

- Detection still runs in the browser, and it is a courtesy rather than a boundary. `M1-ADD-BE-023` must re-detect server-side from the same signature table and treat anything the client says as a hint for the message only.
- Rejections are counted locally but not written to the operational log — nothing is sent to the API for a file that was refused, and this ticket adds no endpoint to send it to.

## 0.2.3 — 2026-08-27

Material can be handed to Askwell. `M1-ADD-FE-022`.

The add-source screen and its files route, and drag-and-drop that works anywhere in the application rather than only on that screen.

### Added

- **`/sources/add/`** — four routes, one working. Files is functional; spreadsheet-or-CSV, database dump and connect-a-database are shown with the milestone they arrive in rather than hidden, so someone whose material is a MySQL export can see it has a home here.
- **Drop anywhere.** A folder of contracts dropped onto the Ask screen is taken and the flow follows it; the user does not navigate first. A folder is expanded, counted and shown before anything starts, and a drop that arrives while another is being read is **queued, never rejected**.
- **Type detection by contents, not by name.** A `.pdf` that is really a PNG is indexed as a PNG and the disagreement is said out loud; a program is refused by name with the fact that nothing was run; an archive is refused with what to do instead. Only the first 4 KB of any file is read.
- **The in-place statement**, once and at full size: nothing is copied, moved or uploaded — which is what someone about to add 40 GB of case files needs before they start.
- A local counter of files added, in `localStorage`. There is no path for it to take off this machine and none is being built (C1).

### Known gaps

- **Nothing is extracted, embedded or searchable yet.** A batch ends at *queued* and says so plainly rather than showing progress that will not move. Records are `M1-ADD-BE-023`; background ingestion and per-file progress are `M1-ADD-ING-025`.
- **A browser will not say where a file lives.** The ticket assumed the drop event gives usable paths; no browser gives them on any platform, so the screen asks once per drop which folder the files came from — the same typed path used to nominate a folder. `M7-TAURI-FE-182` removes the question rather than improving it.
- The estimate is a count and a size, not a duration. Nothing here has yet measured how long embedding takes on a CPU, and an invented number is the one someone plans their afternoon around.

## 0.2.2 — 2026-08-27

Askwell can be told which folders it may read. `M1-ADD-ING-021`.

Askwell indexes in place and copies nothing, so the containers need a route to the user's own files — and this is one narrow, explicit route rather than open filesystem access.

### Added

- **A registry of nominated root directories.** `roots`, its own table, tombstoned on removal so a source underneath can say *why* it stopped being readable rather than merely being unreadable. A path no root covers is never read, and that check resolves symlinks so one link inside a nominated folder cannot stand in for the whole disk.
- `GET /roots`, `POST /roots`, `GET /roots/covering`, `GET /roots/{id}/removal`, `DELETE /roots/{id}`. Registering and removing a folder are decisions records.
- **`ASKWELL_ROOTS_MOUNT`** — one directory bind-mounted read-only into the API and worker at the *same absolute path* it has on the host, so a path means one thing on both sides and needs no translation layer.
- Four reasons a folder can be unreadable, kept apart because they have four different fixes: `not_mounted`, `unavailable` (a drive unplugged — never "deleted"), `unreadable`, `available`.
- **Folders Askwell may read**, in settings: listed with their state, nominated by path, removed against a consequence the API computed rather than one the interface guessed.
- Network shares are permitted, with a warning that indexing will be slow and the share must be connected for a citation to reopen its page.

### Known gaps

- A folder is selected by typing its path. A browser cannot offer a directory dialog; the desktop shell provides one in `M7-TAURI-FE-182`, and only the selection step changes.
- Nominating a folder outside `ASKWELL_ROOTS_MOUNT` is recorded and reports what to set and that the stack must come up again — a container's mounts cannot be changed while it runs. Stated at the moment of registration rather than discovered later.

## 0.2.1 — 2026-08-28

Inference is three processes, not one. [#89](https://github.com/Rumeasiyan/askwell/issues/89), which blocked M1 retrieval.

### Added

- The supervisor manages generation, embedding and reranking independently. One model missing does not stop the others — a user with no reranker can still ask questions.
- `bge-m3` for embeddings (MIT) and `bge-reranker-v2-m3` for ranking (Apache-2.0), both verified against the registry before their names were written down (C9).
- The bridge routes by path, so the containers reach all three through one socket and never learn how many there are.

### Fixed

- **Embeddings were 2560 dimensions where the schema is `vector(1024)`.** They would not have been merely poor for retrieval; the database would have refused them.

## 0.2.0 — 2026-08-27 — M0 lands: it runs

Askwell starts on a clean machine and says it is ready.

```
podman compose up -d      four containers, plus a bridge
scripts/dev.sh inference  llama.cpp, natively, on the host
http://127.0.0.1:8000     the shell, on loopback and nowhere else

database      reachable      assistant: ready
queue         reachable      model:     Qwen3.5-4B-Q4_K_M.gguf
worker        reachable
inference     reachable
egress_proxy  reachable
```

### Added in this release

`M0-SHELL-FE-017a` — the left rail becomes a reachable drawer below the breakpoint, with a scrim that dismisses on click and on Escape, and focus that returns to the control on close. The rail is the only route to sources, memory and settings; hiding it without a way back strands the user.

### What M0 leaves behind

Twenty-one tickets, 216 tests, and a stack whose central claims are checked rather than asserted: an attempt to reach the internet is refused and counted, the API answers on loopback and nowhere else, the audit log cannot be rewritten by the application because it lacks the grant, and every schema invariant is enforced by the database rather than by remembering.

### Known, and written down rather than discovered later

- Inference needs three native processes, not one ([#89](https://github.com/Rumeasiyan/askwell/issues/89)) — embeddings from the generation model are the wrong dimension for the schema, and reranking needs its own model. Blocks M1 retrieval.
- One container, the inference bridge, has host networking. `docs/architecture.md` §5 names it rather than glossing it.
- The 8 GB "slow but usable" claim is still unmeasured ([#49](https://github.com/Rumeasiyan/askwell/issues/49)).

## 0.1.20 — 2026-08-27

`M0-SHELL-FE-017`. The application shell.

### Added

- The three-column layout: left rail, centre column, and the provenance margin **reserved even when empty** — its permanence is what makes an uncited claim visibly wrong.
- Route stubs for Library, Memory and Settings, each with its empty state rather than a blank page.
- A status banner that distinguishes Askwell not answering from the assistant not answering, names what still works, and says so plainly when health cannot be read at all.

### Changed

- The "interface not built" page now also covers the case where it *was* built and the container is holding a replaced directory — which is what actually happens when you rebuild the frontend with the stack up.

## 0.1.19 — 2026-08-27

`M0-MODEL-BE-020`. The two causes of "the assistant is unavailable", kept apart.

### Added

- `GET /assistant` — whether the assistant can answer, the cause when it cannot, the likely fix, and **what still works**. No two causes share a headline, and a test asserts it.
- The supervisor heartbeats while it runs, and handles `SIGTERM`.

### Fixed

- **A killed supervisor left the API reporting the assistant available.** The state file said `ready` and nothing was keeping it current. `SIGTERM` now writes `stopped`; a state older than three missed heartbeats is treated as stopped rather than believed, which covers `SIGKILL` and a machine losing power.

## 0.1.18 — 2026-08-27

`M0-MODEL-BE-019`. The inference client.

### Added

- `askwell.inference.client` — generation, embedding and reranking over the Unix socket, with `InferenceUnavailable` and `InferenceFailed` as separate exceptions so callers can degrade to search rather than showing an error.
- Availability is checked against the supervisor's state file before the request, so the caller gets "no model file at /x.gguf" rather than a connection error.

### Changed

- The supervised process now runs with `--embeddings --pooling mean`.

### Found

- **One process cannot serve all three.** Reranking needs `--reranking` and a reranker model; embeddings from the generation model are 2560 dimensions where the schema is `vector(1024)`. Askwell needs three native processes. Filed as [#89](https://github.com/Rumeasiyan/askwell/issues/89), blocking M1 retrieval.

## 0.1.17 — 2026-08-27

`M0-MODEL-DEPLOY-018`. Native inference, supervised on the host.

### Added

- `deploy/inference/askwell-inference` — a standalone, standard-library-only supervisor. It starts llama.cpp, restarts it with backoff, stops trying after five consecutive failures, and publishes what it knows to a state file.
- `askwell.inference.bridge` — the Unix socket the containers reach inference through, owned by a container because SELinux refuses `container_t` connecting to an `unconfined_t` listener.
- The health surface now reports the loaded model and whether acceleration is in use, which a socket that opens cannot say.
- `scripts/dev.sh inference`.

### Changed

- `ASKWELL_INFERENCE_SOCKET` replaces `ASKWELL_INFERENCE_HOST` and `ASKWELL_INFERENCE_PORT`. Every service is on a network with no route off the machine, so there is no address to dial.
- One container — the inference bridge — runs with host networking, and `docs/architecture.md` §5 now names it rather than glossing it.

## 0.1.16 — 2026-08-27

`M0-SHELL-SESS-016`. The local session — which is not a login and must never become one.

### Added

- A signed session cookie established silently when the interface loads. No password, no roles, no recovery, **no sign-in screen anywhere**.
- The signing secret lives in the `settings` table, generated on first use, so a session survives a stack restart and travels with the data it protects.
- Cross-origin requests refused: another site's page reaching into Askwell with the user's own cookie is the reason the check exists.
- `/health` is exempt and it is the only exemption — a test keeps the list at one entry.

## 0.1.15 — 2026-08-27

`M0-STACK-SEC-012`. Loopback-only, proved from outside the machine.

### Added

- `scripts/verify-localhost-binding.sh` — part of the release checklist. Checks what the port is bound to, what each container publishes, and whether the machine answers on its own addresses from another network namespace.
- A static check on `compose.yaml`, so this runs on every push without a stack being up.
- `docs/architecture.md` §5.0 records what the check does and why its three parts are in that order.

## 0.1.14 — 2026-08-27

`M0-STACK-SEC-011`. The refusal count, as a fact rather than a reassurance.

### Added

- `GET /network` — the proxy's own counters, the recent refusals with their destinations, and the cap on that list stated rather than implied.
- The proxy establishes both counters at startup and records that it is reporting, so an absent counter means "the proxy has never run" rather than "nothing has been refused".

### Changed

- If the counters cannot be read the answer is **unavailable**, never zero. Zero and unknown look identical to a reader and mean opposite things, and "nothing has tried to leave this machine" is the strongest claim the product makes.

## 0.1.13 — 2026-08-27

`M0-STACK-SEC-010`. The default-deny egress proxy — C1's enforcement point.

### Added

- `askwell.egress` and an `egress-proxy` service. It never forwards anything: in local mode there are no allowed destinations, and a test asserts no allowlist has been added.
- A Compose network declared `internal`, so every service but the proxy has **no route off the machine**. Bypassing the proxy finds nothing rather than finding another way out.
- Refusals logged with the destination and the originating service, resolved to a container name, and counted in Redis for the settings surface.
- `docs/architecture.md` §5.1 — how it is built, and how a destination *would* be authorised without authorising any.

### Fixed

- **The health probe was counted as a refused egress attempt.** Askwell checks the proxy by opening a connection and closing it, which added one to the refusal figure every few seconds — turning a number that means "something tried to phone home" into one that means "Askwell is running".

## 0.1.12 — 2026-08-27

`M0-FOUND-DOC-008`. Version and changelog discipline, enforced rather than practised.

### Added

- The frontend reads the version from the repository's `VERSION` file at build time and renders it, so the About screen has something to derive rather than repeat.
- `web/scripts/check-version.mjs` and six tests: the changelog must have an entry for the current version, entries must be newest-first, no version may appear twice, and `web/package.json` must declare no version of its own.

### Fixed

- `0.1.0` had **two** changelog headings — the rewrite and the initial state, both legitimately at that version because no code existed. One version is one entry; a reader looking up `0.1.0` should find all of it in one place. Merged.

## 0.1.11 — 2026-08-27

`M0-FOUND-SEC-007`. The example environment file, and the check that keeps it true.

### Added

- A test that fails when a variable is read by the application, or referenced by `compose.yaml`, and is missing from `.env.example` — and in the other direction, when the file lists something nothing reads.
- Ignore rules for real environment files in every shape people write them, and for generated credential material that does not exist yet. The alternative is adding the rule in the same commit that first writes a key, which is the commit most likely to be in a hurry.

### Changed

- `.env.example` now lists all 23 variables with what each is for. It listed five.

## 0.1.10 — 2026-08-27

`M0-FOUND-DEPLOY-006`. Continuous integration.

### Added

- `.github/workflows/ci.yml` — three jobs on every push and pull request: the API's checks, the database-backed suite, and the frontend. Everything runs through `scripts/dev.sh` inside the same images used locally, so a green run means the same thing in both places.
- `scripts/dev.sh build-api` / `build-web`, and `ASKWELL_CONTAINER` to select podman or docker.

### Changed

- `_env_value` reads the process environment before `.env`, so CI supplies credentials without writing a file it would have to clean up.
- The database host is a value rather than the literal Compose service name.

## 0.1.9 — 2026-08-27

`M0-FOUND-TEST-005`. The test harness, and what it guarantees.

### Added

- A disposable database per run: created, migrated from empty, dropped. Two runs cannot collide, and a database orphaned by a crashed run is swept up by the next one — by age read from its name, so a live run is never taken.
- `api/tests/test_harness.py` — the harness asserts its own promises, including that the migration chain applied from empty **with its invariants**, which creating the schema from model metadata would silently skip.
- `AGENTS.md` §6 records the test convention.

### Fixed

- **`scripts/dev.sh` mounted the repository with `:Z`**, a *private* SELinux relabel, so two containers sharing it relabelled it out from under each other. Two test runs at once failed with a permission error naming a file neither test had touched. Now `:z`.
- **A migration read configuration at import time**, which turned "enumerate the revisions" into "fail because the database password is not set". It is read inside `upgrade()`, where it is used.

## 0.1.8 — 2026-08-27

`M0-DATA-OBS-015`. Hash-chained audit stores, and the trace ring buffer.

### Added

- `askwell.audit` — both database-backed stores chain each record to the hash of the previous one, written in the caller's transaction so a decision that cannot be recorded does not happen. Verification walks the chain and names the record where it breaks.
- `askwell.traces` — a capped file ring buffer that never fails an action. Losing a trace costs nothing visible, because citations are a real table and do not rotate.
- `askwell-verify` — runs the chain check across both stores and exits non-zero on a break. The settings surface arrives in M7.
- 28 database-backed tests and 15 pure ones, including the `jsonb` round trip, racing writes, and a guard that the word "immutable" is only ever used to deny it.

### Fixed

- **A chain whose first record was deleted reported as intact.** `MISSING_GENESIS` has no single record to name, `first_break` was therefore `None`, and `intact` was derived from it. A verifier that says "fine" about a chain whose start was removed is worse than no verifier.
- **Verification read the chain in timestamp order** and reported perfectly good chains as broken when two records landed close together. It follows the links now: a chain defines its own order, and every available ordering column is worse.

## 0.1.7 — 2026-08-27

`M0-DATA-DB-014`. The invariants, in the migration that creates the tables.

### Added

- Five invariants the ORM will not express: no `UPDATE`/`DELETE`/`TRUNCATE` grant on either audit table (C6); one live version per `(source_id, sha256)`; a chunk with cleared content cannot keep its embedding; a clarification marked answered must carry an answer; and the non-cascading citation foreign key.
- `deploy/postgres/10-roles.sh` — creates `askwell_app` and `askwell_readonly`. Askwell connects as `askwell_app`, which owns nothing.
- `scripts/dev.sh test-db` — 18 database-backed tests, deselected from the default run and failing rather than skipping when the database is absent.

### Changed

- **The application no longer connects as the table owner.** An owner bypasses its own grants, so the append-only guarantee would have been decorative — the `REVOKE` succeeds, the privilege listing looks right, and the application can still rewrite every audit record. See `docs/decisions.md`.
- `.env.example` carries `POSTGRES_APP_PASSWORD` and `POSTGRES_READONLY_PASSWORD`.

## 0.1.6 — 2026-08-27

`M0-DATA-DB-013`. The whole v1 schema in one reversible migration.

### Added

- `askwell.db` — the declarative base, the engine, and the thirteen tables of `docs/architecture.md` §7. No `organisations`, no `users`, no roles.
- One migration creating all of it, hand-edited after autogeneration for the vector extension, the configured embedding dimension, `content_tsv` as a generated column, and the Tamil text search configuration kept as a hedge.
- `ASKWELL_EMBEDDING_DIMENSIONS` — the width of every embedding column, so changing model is a configuration change plus a re-embed rather than a schema edit.
- `scripts/dev.sh db` and `scripts/dev.sh psql`.
- Fourteen model tests asserting the properties §7 calls load-bearing, without needing a database.

### Fixed

- **Column defaults were Python-side only.** They applied to rows the ORM inserted and to nothing else, so a migration, a `psql` session or a repair script hit a `NOT NULL` violation on a column that appeared to have a default. Found by inserting a document by hand. They are `server_default` now, and a test asserts it.

### Changed

- psycopg 3 is the database driver for both the async application and Alembic's synchronous path. asyncpg is faster on paper but cannot do the sync half, and two drivers means two sets of type adapters and two failure modes on a machine where nobody is watching.

## 0.1.5 — 2026-08-27

`M0-STACK-DEPLOY-009`. The stack comes up with one command.

### Added

- `compose.yaml` — `api`, `postgres` (pgvector, PG 18.6), `redis` and `worker`, with named volumes, health declarations and startup ordering. The egress proxy, sandbox database and voice are deliberately absent; they arrive in their own tickets.
- `askwell.worker` — the arq worker and a `ping` job, which is the cheapest end-to-end proof the queue is wired up.
- `.env.example` — the variables the stack needs. `M0-FOUND-SEC-007` completes it.

### Fixed

- **The worker was reported unreachable while running.** It was probed by opening a TCP socket, and an arq worker consumes a queue without listening on anything — so a healthy worker read as down, every time. It is now probed through the health record arq publishes into Redis, which distinguishes "the queue is down" from "the queue is up and the worker is not running". Those need different actions from the user.

### Changed

- `ASKWELL_WORKER_HOST` and `ASKWELL_WORKER_PORT` are gone, replaced by `ASKWELL_WORKER_HEALTH_KEY`.

## 0.1.4 — 2026-08-27

`M0-FOUND-DEPLOY-004`. The API serves the interface. The `web` container is gone from the topology.

### Added

- `askwell.interface` — static asset serving with a deliberate route fallback, per-file cache behaviour, and containment checked after `resolve()` so `..` and symlinks are already collapsed.
- `ASKWELL_WEB_ASSETS_DIR` — where the built interface lives.
- `web/app/not-found.tsx` — the product's own not-found page. Next's default is hardcoded black-on-white and drops the user out of the interface entirely.
- Fourteen tests covering the two requirements that pull against each other, five path-escape attempts and a symlink, cache headers per file kind, and the missing-build case.

### Changed

- Content-hashed assets are cached for a year and marked immutable; HTML is `no-cache`. The HTML is what points at the hashed filenames, so caching both the same way leaves a user on the old bundle after an update with no reason to suspect it.
- A missing build returns a readable page naming the directory and the command, at HTTP 503 — not a blank page. `/health` keeps working, which is what someone with a broken install actually needs.

## 0.1.3 — 2026-08-26

`M0-FOUND-FE-003`. The frontend, pinned as one verified set.

### Added

- `web/` — Next.js 16.3.3, React 19.2.8, Tailwind 4.3.3, pnpm 11.24.0, built to static assets in `web/out`. Every dependency is an exact version; there is not a single range operator in `package.json`.
- `web/app/globals.css` — the design tokens from `docs/ux/design-system.md` §2–§4, defined once. `--rule-strong` is its own token, not an alias of `--rule`. Depth is `--inset` and `--drop`, per theme.
- `web/scripts/contrast.mjs` — measures all 19 token pairs in both themes and fails below 4.5:1 for text or 3:1 for UI lines. Figures recorded in `docs/ux/design-system.md` §8.
- `web/scripts/check-tokens.mjs` — fails on a literal colour or a literal shadow anywhere outside the token definition, and on a depth token that does not differ between themes.
- `web/scripts/check-offline.mjs` — scans the built output for anything that would reach the network, by position rather than by pattern (C1).
- `web/Dockerfile` and `scripts/dev.sh web-*` — the Node toolchain lives in an image, like the Python one. Every frontend command runs with `--network=none` except `web-install`.

### Changed

- `docs/ux/design-system.md` §8 now records measured contrast figures rather than asserting a floor.

## 0.1.2 — 2026-08-26

`M0-FOUND-BE-002`. The API application, its configuration, its logging and its health surface.

### Added

- `askwell.config` — typed settings from `ASKWELL_*` environment variables. Refuses to start on unusable configuration and names every offending variable at once, by the name a person actually typed. An unknown `ASKWELL_*` variable is reported rather than ignored, because a typo otherwise leaves the setting it was meant to change silently on its default.
- `askwell.logging` — structlog, JSON to stderr, ISO-8601 UTC timestamps. Redaction is a processor, not a convention: anything whose key looks like a credential, and every `SecretStr` whatever its key is called, is replaced at any depth. Standard-library logs — uvicorn's included — are rendered by the same renderer, so the stream is parseable throughout.
- `askwell.health` — five components probed independently and concurrently. Name resolution is separate from connection so that "does not resolve" and "is not answering yet" are different messages, because they need different actions from the user.
- `askwell.app` — FastAPI application, `GET /health`, startup and shutdown logging with resolved profile and component states, and an error handler that shows the exception in development and a stated reason otherwise.
- `askwell-api` console entry point.

### Changed

- Logger caching is off. structlog binds a cached logger to whatever configuration was live at first use, and modules take their loggers at import time — before configuration is read — so a cached logger silently ignores it.

## 0.1.1 — 2026-08-26

First product code. `M0-FOUND-DEPLOY-001`.

### Added

- `api/Dockerfile` — API image pinned to Python 3.12, carrying `uv`, `ruff`, `mypy` and `pytest` inside it. The host needs Podman and nothing else. The build fails loudly if the base image ever drifts off 3.12.
- `api/pyproject.toml`, `api/uv.lock` — dependency manifest and lockfile. The lockfile is the pin; the manifest holds only bounds.
- `api/hatch_build.py` — reads the package version from the repository's `VERSION` file, so there is no second version to maintain.
- `api/src/askwell/` — the package, with version resolution that prefers the `VERSION` file over stamped metadata so a bump is visible without reinstalling.
- `api/tests/test_version.py` — five tests, including one that scans the tree for a second declared version string.
- `scripts/dev.sh` — runs lint, format, typecheck and tests inside the image against the working tree. Every command runs with `--network=none` except `lock`, which needs an index and says so.

### Changed

- `AGENTS.md` §5 — the commands table now lists commands that have been run, not commands that are intended.
- `AGENTS.md` §7 — tickets inside a phase are `PATCH`; the phase landing is the `MINOR`. Previously the two rules in that section contradicted each other for any phase with more than one ticket.

## 0.1.0 — 2026-08-10

Two things happened at this version and the number did not move, deliberately:
no application code existed, so no user-visible behaviour changed. They are
recorded here as one entry rather than two headings, because one version is
one entry — a reader looking up `0.1.0` should find all of it in one place.

### The rewrite

Product repositioned. The previous documentation described on-premise software sold to government ministries; Askwell is a free local install for one individual professional. Version unchanged — no code exists, so no user-visible behaviour changed.

### Added

- `docs/architecture.md` — technical decisions, topology, auth, data model, retrieval, security. Split out of the PRD.
- `docs/data-sources.md` — files, CSV, SQL dump import with sandbox isolation, live connections.
- `docs/memory-and-clarification.md` — the clarification loop and permanent memory. New capability and the product's differentiator.
- `docs/audit-log.md` — three separate stores with different retention and failure behaviour; hash-chained.
- `docs/build-plan.md` — phases, acceptance criteria, quality gate, repo layout.
- Constraint C3: an imported dump is untrusted code and loads only into an isolated sandbox Postgres.
- Quality-gate category for memory application (15 tasks) — without it the differentiator has no test.

### Changed

- `docs/PRD.md` rewritten as a **business-only** document, shareable as a pitch. All implementation detail moved out.
- Single user, single machine. No organisations, users, roles, RBAC, seat tiers, licence keys or high availability.
- C1 now permits an explicit per-conversation online-AI opt-in instead of forbidding all egress.
- C6 restated as **tamper-evident, not immutable** — the user owns the disk, and any stronger claim is false.
- Authentication reduced to a local session plus an optional at-rest passphrase. JWT/Argon2id/TOTP/blacklist removed.
- Deployment profiles rebuilt around personal hardware; floor drops to 8GB and the installer warns rather than refuses.
- `docs/success-metrics.md` fully re-derived — there is no pilot. Adds clarification-loop metrics.
- `docs/states-and-edge-cases.md` — licence, seat-cap, session-expiry and permission-denial states removed; disk-budget, online-mode and clarification states added.
- Issue templates and labels updated to the new constraint numbering.

### Settled defaults

- Clarification cap of 5 questions per source, with a documented ranking for what makes the cut.
- Log budget 2 GB or 5% of free disk, whichever smaller; 12-month interaction retention; decisions never pruned.
- Sandbox caps of 5 GB and 10 minutes per import.
- v1 imports PostgreSQL dumps only — MySQL and SQL Server via live connection or CSV.
- No telemetry through Phase 6, accepting that primary retention metrics become unobservable.

### Removed

- Constraint C7-as-was (column-level access control per role) — it protected one role from another, and there are no roles.
- Multi-node high availability, permanently (#4).

### The initial state

First versioned state. No application code — the repository is documentation only, Phase 0 not yet started.

### Added

- `AGENTS.md` — working agreements, hard constraints, commands, conventions, versioning, tracker and session workflow.
- `docs/decisions.md` — append-only decision log, seeded from git history and `docs/PRD.md` §5.1.
- `VERSION` — canonical application version, single source of truth.
- `CHANGELOG.md` — this file.
- `.github/ISSUE_TEMPLATE/` — issue templates for tasks, bugs, and blocked decisions.
- `README.md` — was missing; the repository had no entry point for a human arriving cold.
- `docs/success-metrics.md` — what "working" means in numbers in production, distinct from the model eval gate. Abstention rate reframed as a 5–20% band with a citation-correctness counter-metric, because it is trivially gamed by lowering the retrieval threshold.
- `docs/states-and-edge-cases.md` — every state a user can be in across chat, ingestion, database QA, voice, admin, plus collected empty states. Surfaced six product decisions with no PRD answer (issues #10–#15).
- Repository labels for build phase (`phase:0`…`phase:6`) and hard constraints (`constraint:*`).

### Changed

- `CLAUDE.md` reduced to a shim importing `AGENTS.md`; its rules now live in `AGENTS.md`.
- **v1 scope is now English-only.** Tamil and Sinhala moved out of the phase list to v2 (`docs/PRD.md` §1.2). Resolves §11 items 1 and 2, closing issues #1 and #2.
  - Phase 4 estimate 2 weeks → 1.5; acceptance is an English round trip only, no language detection.
  - `edge` profile no longer degraded for voice — whisper `small` serves all three profiles.
  - Eval gate 160 → 140 tasks; Tamil category removed, `eval/suites/tamil.jsonl` not created.
  - Phase 1 acceptance changed from a scanned Tamil PDF to a scanned English one.
  - Hedges kept so Tamil is later work rather than a corpus migration: `bge-m3` embeddings, Tamil-aware Postgres FTS config, `tam` OCR traineddata, pluggable TTS interface.
  - Label `tamil` replaced by `v2:language`.
- `PRD.md` and `BRAIN.md` moved into `docs/`. Root now holds only what a tool or convention requires there.
- `docs/PRD.md` §10 split into what exists and what is planned, with a table of which directory arrives in which phase — the previous single tree described almost nothing that existed, with no marker saying so.

### Fixed

- `docs/PRD.md` §5.2 container count: six → seven.
- `docs/PRD.md` §5.3 deployment-profile models: `Qwen3.5 4B` → `Qwen3 4B`, `Qwen3.6 27B` → `Qwen3 32B` (neither original was a real release).
- `docs/PRD.md` §7 eval harness path: `bench/` → `eval/bench.py`, matching §10.
- `docs/PRD.md` owner name, and `Rumesh` → `Rumeasiyan` in `docs/PRD.md` §11 and `docs/BRAIN.md`.
- `docs/BRAIN.md` blocker 4 no longer contradicts `docs/PRD.md` §11.4 about whether it affects Phase 0.
- `prd.md` renamed to `PRD.md` (the reference in §10 was already capitalised), then moved with `BRAIN.md` into `docs/`.
