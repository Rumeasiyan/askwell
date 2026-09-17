"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type ClarificationGroup,
  type ClarificationsState,
  type EvidenceDisplay,
  type Reprocessing,
  type SessionTally,
  NONE_PENDING_COPY,
  SKIPPED_FOR_EMPTY_ANSWER_COPY,
  UNDO_WINDOW_SECONDS,
  answerClarification,
  cappedSentence,
  completionSentence,
  currentInference,
  dismissGroup,
  emptySessionTally,
  evidenceDisplay,
  fetchClarifications,
  groupSentence,
  isBlankAnswer,
  mergeIncoming,
  recordAnswered,
  recordDismissed,
  recordSkipped,
  rowCountLabel,
  savedConfirmation,
  skipClarification,
  tallyAnswer,
  tallySkip,
  totalSentence,
  undoAnswer,
} from "@/lib/clarifications";
import { subscribeIngest, type IngestState } from "@/lib/ingest";
import { ReapplyProgress } from "./reapply-progress";

/** How long the completion state (`../ux/clarifications.md` §5) stays up
 * before handing back to the plain empty state, on its own. */
const COMPLETION_VISIBLE_MS = 6000;

/**
 * The clarifications screen. `docs/ux/clarifications.md`, `M3-REVIEW-FE-072`
 * through `-074`.
 *
 * A single reviewable list, newest source first, grouped by source, with a
 * count per group and a total at the top — never a wizard, never one at a
 * time. Save, skip, skip-all and undo are wired here (`M3-REVIEW-FE-074`);
 * every action is local state plus one API call, never a route change, so
 * "advances to the next item" is just the acted-on item leaving the list.
 */
export function ClarificationsScreen() {
  const [state, setState] = useState<ClarificationsState | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [sessionTally, setSessionTally] = useState<SessionTally>(emptySessionTally());
  const [completionVisible, setCompletionVisible] = useState(false);
  const [reapplyJobs, setReapplyJobs] = useState<{ id: string; subject: string }[]>([]);
  const [ingestingSourceIds, setIngestingSourceIds] = useState<Set<string>>(new Set());

  // Read inside `removeItem`/`removeGroup` so those plain event handlers can
  // tell, synchronously, whether the item they just resolved was the last
  // one pending — without making `state` itself a dependency (which would
  // rebuild the callback, and the undo/removal timers that close over it,
  // on every fetch). Kept current by a no-op-setState effect below, which
  // `react-hooks/set-state-in-effect` has nothing to say about: it never
  // calls a state setter, only assigns a ref.
  const stateRef = useRef<ClarificationsState | null>(null);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const completionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (completionTimer.current !== null) clearTimeout(completionTimer.current);
    },
    [],
  );

  useEffect(() => {
    const controller = new AbortController();
    let live = true;

    fetchClarifications(controller.signal)
      .then((first) => {
        if (live) setState(first);
      })
      .catch((error: unknown) => {
        if (live && !controller.signal.aborted) setFailure(String(error));
      });

    // Issue 272: a screen left open during ingestion must pick up newly-raised
    // questions on its own. Refetching and merging (never replacing) on
    // every ingest push means an in-progress answer or an undo countdown is
    // never disturbed by a question that landed a moment later.
    const stop = subscribeIngest((ingest: IngestState) => {
      if (!live) return;
      setIngestingSourceIds(
        new Set(ingest.sources.filter((source) => source.outstanding > 0).map((source) => source.id)),
      );
      fetchClarifications()
        .then((fresh) => {
          if (live) setState((current) => (current === null ? fresh : mergeIncoming(current, fresh)));
        })
        .catch(() => {
          // A missed pickup is invisible, not alarming — the next push, or a
          // manual reload, catches up.
        });
    });

    return () => {
      live = false;
      controller.abort();
      stop();
    };
  }, []);

  // `../ux/clarifications.md` §5, "All answered": shown once, for a fixed
  // window, the moment the item or group just resolved was the last thing
  // pending. A plain call from an event handler, not a `useEffect` body — the
  // lint rule against synchronous `setState` in an effect does not apply
  // here, and it is what lets the completion state key off the exact action
  // that emptied the queue rather than a derived `hasGroups` transition that
  // cannot tell "just emptied" apart from "was already empty".
  const maybeShowCompletion = useCallback((totalAfter: number) => {
    if (totalAfter !== 0) return;
    setCompletionVisible(true);
    if (completionTimer.current !== null) clearTimeout(completionTimer.current);
    completionTimer.current = setTimeout(() => {
      setCompletionVisible(false);
      setSessionTally(emptySessionTally());
    }, COMPLETION_VISIBLE_MS);
  }, []);

  const removeItem = useCallback(
    (itemId: string, outcome: { kind: "answered"; reprocessing: Reprocessing } | { kind: "skipped" }) => {
      setSessionTally((tally) =>
        outcome.kind === "answered" ? tallyAnswer(tally, outcome.reprocessing) : tallySkip(tally),
      );
      const current = stateRef.current;
      if (current === null) return;
      const groups = current.groups
        .map((group) => {
          if (!group.items.some((item) => item.id === itemId)) return group;
          const items = group.items.filter((item) => item.id !== itemId);
          return { ...group, items, count: items.length };
        })
        .filter((group) => group.items.length > 0 || group.capped > 0);
      const total = groups.reduce((sum, group) => sum + group.items.length, 0);
      setState({ ...current, groups, total });
      maybeShowCompletion(total);
    },
    [maybeShowCompletion],
  );

  const removeGroup = useCallback(
    (sourceId: string, removedIds: Set<string>) => {
      setSessionTally((tally) => tallySkip(tally, removedIds.size));
      const current = stateRef.current;
      if (current === null) return;
      const groups = current.groups
        .map((group) => {
          if (group.source_id !== sourceId) return group;
          const items = group.items.filter((item) => !removedIds.has(item.id));
          return { ...group, items, count: items.length };
        })
        .filter((group) => group.items.length > 0 || group.capped > 0);
      const total = groups.reduce((sum, group) => sum + group.items.length, 0);
      setState({ ...current, groups, total });
      maybeShowCompletion(total);
    },
    [maybeShowCompletion],
  );

  const addReapplyJob = useCallback((jobId: string, subject: string) => {
    setReapplyJobs((jobs) => (jobs.some((job) => job.id === jobId) ? jobs : [...jobs, { id: jobId, subject }]));
  }, []);

  const removeReapplyJob = useCallback((jobId: string) => {
    setReapplyJobs((jobs) => jobs.filter((job) => job.id !== jobId));
  }, []);

  const totalPending = state === null ? null : state.groups.reduce((sum, group) => sum + group.items.length, 0);
  const hasGroups = state !== null && state.groups.length > 0;

  return (
    <section className="flex flex-col gap-4">
      <div>
        <h1 style={{ fontSize: "var(--t-display)", lineHeight: "var(--t-display-lh)" }}>
          Clarifications
        </h1>
        {totalPending !== null && totalPending > 0 ? (
          <p className="ask-micro mt-1">{totalSentence(totalPending)} pending</p>
        ) : null}
      </div>

      {reapplyJobs.length > 0 ? (
        <div className="flex flex-col gap-2">
          {reapplyJobs.map((job) => (
            <ReapplyProgress
              key={job.id}
              jobId={job.id}
              subject={job.subject}
              onDone={() => removeReapplyJob(job.id)}
            />
          ))}
        </div>
      ) : null}

      {failure !== null ? (
        <p className="ask-prose" style={{ color: "var(--alarm)" }}>
          Askwell is not answering about clarifications.
        </p>
      ) : state === null ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          Reading the queue…
        </p>
      ) : !hasGroups ? (
        completionVisible ? <CompletionBanner tally={sessionTally} /> : <EmptyClarifications />
      ) : (
        <div className="flex flex-col gap-5">
          {state.groups.map((group) => (
            <SourceGroup
              key={group.source_id}
              group={group}
              cap={state.cap}
              ingesting={ingestingSourceIds.has(group.source_id)}
              onItemRemoved={removeItem}
              onGroupDismissed={removeGroup}
              onReapplyJob={addReapplyJob}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function EmptyClarifications() {
  return (
    <p
      className="ask-prose px-4 py-3"
      style={{ background: "var(--surface)", borderRadius: "var(--radius)" }}
    >
      {NONE_PENDING_COPY}
    </p>
  );
}

/** `../ux/clarifications.md` §5, "All answered" — names what improved,
 * honestly, then `ClarificationsScreen`'s own timer hands back to
 * `EmptyClarifications`. */
function CompletionBanner({ tally }: { tally: SessionTally }) {
  return (
    <p
      className="ask-prose px-4 py-3"
      style={{ background: "var(--surface)", borderRadius: "var(--radius)" }}
    >
      {completionSentence(tally)}
    </p>
  );
}

/** `../ux/clarifications.md` §5, "Capped" — honest about what was not asked,
 * and routes to where it can be corrected. Shown for a source whether or not
 * it still has anything pending (issue 297). */
function CappedBanner({ cap }: { cap: number }) {
  return (
    <div
      className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
      style={{ background: "var(--surface)", borderRadius: "var(--radius)" }}
    >
      <p className="ask-prose">{cappedSentence(cap)}</p>
      <a className="ask-navigates ask-micro" href="/memory">
        Review in Memory
      </a>
    </div>
  );
}

type AnswerOutcome = { kind: "answered"; reprocessing: Reprocessing } | { kind: "skipped" };

function SourceGroup({
  group,
  cap,
  ingesting,
  onItemRemoved,
  onGroupDismissed,
  onReapplyJob,
}: {
  group: ClarificationGroup;
  cap: number;
  ingesting: boolean;
  onItemRemoved: (itemId: string, outcome: AnswerOutcome) => void;
  onGroupDismissed: (sourceId: string, removedIds: Set<string>) => void;
  onReapplyJob: (jobId: string, subject: string) => void;
}) {
  const [dismissing, setDismissing] = useState(false);
  const [dismissFailure, setDismissFailure] = useState<string | null>(null);

  const handleDismissAll = useCallback(() => {
    setDismissing(true);
    setDismissFailure(null);
    dismissGroup(group.source_id)
      .then((dismissed) => {
        recordDismissed(dismissed.length);
        onGroupDismissed(group.source_id, new Set(dismissed));
      })
      .catch((error: unknown) => setDismissFailure(String(error)))
      .finally(() => setDismissing(false));
  }, [group.source_id, onGroupDismissed]);

  // Issue 297: a source can be capped with nothing left pending — the
  // disclosure still owes a group, just with no items and no "Skip all".
  if (group.items.length === 0) {
    return (
      <div className="flex flex-col gap-2">
        <h2 style={{ fontSize: "var(--t-ui)" }}>{group.source_name}</h2>
        <CappedBanner cap={cap} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <h2 style={{ fontSize: "var(--t-ui)" }}>{group.source_name}</h2>
        <div className="flex items-center gap-3">
          <span className="ask-micro">{groupSentence(group.count)}</span>
          <button
            type="button"
            className="ask-navigates ask-micro"
            onClick={handleDismissAll}
            disabled={dismissing}
          >
            Skip all
          </button>
        </div>
      </div>
      {ingesting ? (
        <p className="ask-micro" style={{ color: "var(--muted)" }}>
          Still indexing this source — already searchable.
        </p>
      ) : null}
      {dismissFailure !== null ? (
        <p className="ask-micro" style={{ color: "var(--alarm)" }}>
          Askwell could not dismiss these: {dismissFailure}
        </p>
      ) : null}
      {group.capped > 0 ? <CappedBanner cap={cap} /> : null}
      <div className="flex flex-col gap-2">
        {group.items.map((item) => (
          <ClarificationItemRow
            key={item.id}
            item={item}
            onRemoved={(outcome) => onItemRemoved(item.id, outcome)}
            onReapplyJob={onReapplyJob}
          />
        ))}
      </div>
    </div>
  );
}

type ItemPhase =
  | { kind: "pending" }
  | { kind: "submitting" }
  | { kind: "saved"; message: string; memoryId: string; secondsLeft: number }
  | { kind: "undoing" }
  | { kind: "skipped"; message: string }
  | { kind: "error"; message: string };

/**
 * One question's anatomy: subject, question, evidence, answer, current
 * inference, and — this ticket's own territory — save, skip, and the undo
 * window a save opens. `../ux/clarifications.md` §3 and §4.
 */
function ClarificationItemRow({
  item,
  onRemoved,
  onReapplyJob,
}: {
  item: ClarificationGroup["items"][number];
  onRemoved: (outcome: AnswerOutcome) => void;
  onReapplyJob: (jobId: string, subject: string) => void;
}) {
  const inference = currentInference(item.evidence);
  const evidence = evidenceDisplay(item.evidence);
  const isDiscrete = item.options !== null && item.options.length > 0;
  const inputRef = useRef<HTMLInputElement | null>(null);

  const [phase, setPhase] = useState<ItemPhase>({ kind: "pending" });
  const removalTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const countdownTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearTimers = useCallback(() => {
    if (removalTimer.current !== null) clearTimeout(removalTimer.current);
    if (countdownTimer.current !== null) clearInterval(countdownTimer.current);
    removalTimer.current = null;
    countdownTimer.current = null;
  }, []);

  useEffect(() => clearTimers, [clearTimers]);

  const submit = useCallback(
    async (rawAnswer: string) => {
      if (isBlankAnswer(rawAnswer)) {
        setPhase({ kind: "submitting" });
        try {
          await skipClarification(item.id);
          recordSkipped();
          setPhase({ kind: "skipped", message: SKIPPED_FOR_EMPTY_ANSWER_COPY });
          removalTimer.current = setTimeout(() => onRemoved({ kind: "skipped" }), 1500);
        } catch (error: unknown) {
          setPhase({ kind: "error", message: String(error) });
        }
        return;
      }

      setPhase({ kind: "submitting" });
      try {
        const result = await answerClarification(item.id, rawAnswer.trim());
        recordAnswered();
        if (result.reapplyJobId !== null) {
          onReapplyJob(result.reapplyJobId, item.subject);
        }
        let secondsLeft = UNDO_WINDOW_SECONDS;
        setPhase({
          kind: "saved",
          message: savedConfirmation(result.reprocessing),
          memoryId: result.memoryId,
          secondsLeft,
        });
        countdownTimer.current = setInterval(() => {
          secondsLeft -= 1;
          if (secondsLeft <= 0) {
            clearTimers();
            return;
          }
          setPhase((current) =>
            current.kind === "saved" ? { ...current, secondsLeft } : current,
          );
        }, 1000);
        removalTimer.current = setTimeout(
          () => onRemoved({ kind: "answered", reprocessing: result.reprocessing }),
          UNDO_WINDOW_SECONDS * 1000,
        );
      } catch (error: unknown) {
        setPhase({ kind: "error", message: String(error) });
      }
    },
    [item.id, item.subject, onRemoved, onReapplyJob, clearTimers],
  );

  const handleSkip = useCallback(async () => {
    setPhase({ kind: "submitting" });
    try {
      await skipClarification(item.id);
      recordSkipped();
      setPhase({ kind: "skipped", message: "Skipped." });
      removalTimer.current = setTimeout(() => onRemoved({ kind: "skipped" }), 1000);
    } catch (error: unknown) {
      setPhase({ kind: "error", message: String(error) });
    }
  }, [item.id, onRemoved]);

  const handleUndo = useCallback(
    (memoryId: string) => {
      clearTimers();
      setPhase({ kind: "undoing" });
      undoAnswer(item.id, memoryId)
        .then(() => {
          setPhase({ kind: "pending" });
          if (inputRef.current) inputRef.current.value = inference ?? "";
        })
        .catch((error: unknown) => setPhase({ kind: "error", message: String(error) }));
    },
    [item.id, inference, clearTimers],
  );

  const handleOption = useCallback(
    (option: string) => {
      void submit(option);
    },
    [submit],
  );

  const busy = phase.kind === "submitting" || phase.kind === "undoing";

  return (
    <div
      className="flex flex-col gap-2 px-4 py-3"
      style={{ background: "var(--surface)", borderRadius: "var(--radius)" }}
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className="ask-micro" style={{ fontFamily: "var(--font-mono)" }}>
          {item.subject}
        </span>
      </div>
      <p className="ask-prose">{item.question}</p>
      <EvidenceBlock evidence={evidence} />

      {phase.kind === "saved" ? (
        <ItemConfirmation phase={phase} onUndo={() => handleUndo(phase.memoryId)} />
      ) : phase.kind === "skipped" ? (
        <ItemConfirmation phase={phase} />
      ) : (
        <>
          {isDiscrete ? (
            <div className="flex flex-wrap gap-2" role="group" aria-label="Choose an answer">
              {(item.options ?? []).map((option) => (
                <button
                  key={option}
                  type="button"
                  className="ask-navigates px-3"
                  disabled={busy}
                  onClick={() => handleOption(option)}
                  style={{
                    minHeight: "var(--control-height)",
                    background: "var(--paper)",
                    border: "1px solid var(--rule)",
                    borderRadius: "var(--radius)",
                    fontFamily: "var(--font-mono)",
                    fontSize: "var(--t-ui)",
                    color: "var(--ink)",
                  }}
                >
                  {option}
                </button>
              ))}
            </div>
          ) : (
            <input
              ref={inputRef}
              type="text"
              defaultValue={inference ?? ""}
              aria-label={`Your answer: ${item.question}`}
              className="ask-input px-3"
              disabled={busy}
              onKeyDown={(event) => {
                if (event.key === "Enter") void submit(event.currentTarget.value);
              }}
              style={{ fontFamily: "var(--font-text)", fontSize: "var(--t-ui)" }}
            />
          )}
          {phase.kind === "error" ? (
            <p className="ask-micro" style={{ color: "var(--alarm)" }}>
              Askwell could not save that: {phase.message}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center justify-between gap-3 mt-1">
            <div className="flex gap-2">
              {!isDiscrete ? (
                <button
                  type="button"
                  className="ask-navigates px-4"
                  disabled={busy}
                  onClick={() => void submit(inputRef.current?.value ?? "")}
                  style={{
                    minHeight: "var(--control-height)",
                    background: "var(--ink)",
                    color: "var(--paper)",
                    border: "1px solid var(--ink)",
                    borderRadius: "var(--radius)",
                    fontSize: "var(--t-ui)",
                  }}
                >
                  Save
                </button>
              ) : null}
              <button
                type="button"
                className="ask-navigates px-4"
                disabled={busy}
                onClick={() => void handleSkip()}
                style={{
                  minHeight: "var(--control-height)",
                  background: "var(--ink)",
                  color: "var(--paper)",
                  border: "1px solid var(--ink)",
                  borderRadius: "var(--radius)",
                  fontSize: "var(--t-ui)",
                }}
              >
                Skip
              </button>
            </div>
            {inference !== null ? (
              <span className="ask-micro flex items-center gap-1.5" style={{ color: "var(--inferred)" }}>
                <span className="ask-confidence-marker" aria-hidden="true" />I guessed: {inference}
              </span>
            ) : null}
          </div>
        </>
      )}
    </div>
  );
}

function ItemConfirmation({
  phase,
  onUndo,
}: {
  phase: Extract<ItemPhase, { kind: "saved" | "skipped" }>;
  onUndo?: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <p className="ask-prose">{phase.message}</p>
      {phase.kind === "saved" && onUndo !== undefined ? (
        <button type="button" className="ask-navigates ask-micro" onClick={onUndo}>
          Undo ({phase.secondsLeft}s)
        </button>
      ) : null}
    </div>
  );
}

/** Exported for `ask-screen.tsx`'s inline clarification (`M3-INLINE-FE-085`)
 * — the same evidence rendering, whether the question is answered here or
 * inline in the conversation. */
export function EvidenceBlock({ evidence }: { evidence: EvidenceDisplay | null }) {
  const mono = { fontFamily: "var(--font-mono)", color: "var(--muted)" } as const;

  if (evidence === null) {
    return (
      <p className="ask-micro" style={mono}>
        No evidence available.
      </p>
    );
  }

  switch (evidence.kind) {
    case "distribution":
      return (
        <p className="ask-micro" style={mono}>
          {rowCountLabel(evidence.rowCount)}. Values:{" "}
          {evidence.values.map((entry) => `${entry.value} (${entry.count.toLocaleString("en-US")})`).join(" · ")}
          {evidence.remainderCount > 0
            ? ` · ${evidence.remainderCount.toLocaleString("en-US")} more`
            : ""}
        </p>
      );
    case "passage":
      return evidence.samples.length > 0 ? (
        <div className="flex flex-col gap-1">
          {evidence.samples.map((sample, index) => (
            <p key={index} className="ask-micro" style={mono}>
              {sample.document}
              {sample.page !== null ? `, p. ${sample.page}` : ""} — {sample.text}
            </p>
          ))}
        </div>
      ) : (
        <p className="ask-micro" style={mono}>
          No evidence available.
        </p>
      );
    case "poor_scan":
      return evidence.extracted.length > 0 ? (
        <div className="flex flex-col gap-1">
          <p className="ask-micro" style={mono}>
            {evidence.pages.length} of {evidence.totalPages} page(s) scanned poorly.
          </p>
          {evidence.extracted.map((sample, index) => (
            <p key={index} className="ask-micro" style={mono}>
              p. {sample.page} — {sample.text}
            </p>
          ))}
        </div>
      ) : (
        <p className="ask-micro" style={mono}>
          No evidence available.
        </p>
      );
    case "contradiction":
      return (
        <div className="flex flex-col gap-1">
          {evidence.passages.map((passage, index) => (
            <p key={index} className="ask-micro" style={mono}>
              {passage.document} says {passage.value}
              {passage.date !== null ? ` (${passage.date})` : ""} — {passage.text}
            </p>
          ))}
        </div>
      );
    case "unavailable":
      return (
        <p className="ask-micro" style={mono}>
          No evidence available{evidence.reason !== "" ? ` — ${evidence.reason}` : ""}.
        </p>
      );
  }
}
