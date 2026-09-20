"use client";

/**
 * The trace panel: "How did you get this?" — `docs/ux/trace.md`, `M5-TRACE-
 * FE-119`.
 *
 * A panel over Ask, not a page (the spec's own Route line) — the reader is
 * investigating one answer and must not lose their place in the
 * conversation, so this is an overlay `<dialog>`-shaped `<div>` in the same
 * pattern `rail-drawer.tsx` already established, not a navigation.
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { useAsk } from "@/components/ask/ask-state";
import { MemoryChip } from "@/components/ask/memory-chip";
import { useDeletion } from "@/components/ask/provenance-margin";
import { QueryDisclosure } from "@/components/ask/sql-result-table";
import { documentHref, pageLabel, type CitationCard } from "@/lib/citations";
import { fetchFactDetail, type FactDetail } from "@/lib/memory-chips";
import {
  buildTraceCopyText,
  fetchTrace,
  hitCitation,
  memoryFactRefs,
  recordTraceCopy,
  recordTraceOpened,
  retrievalThreshold,
  retrievedHits,
  sqlStepInfo,
  toolCeilingPendingCalls,
  toolInjectionPatterns,
  traceRows,
  type MemoryFactRef,
  type PendingToolCall,
  type RetrievedHit,
  type TraceData,
  type TraceRow,
  type TraceStep,
} from "@/lib/trace";

/** How often an open panel re-polls while its own turn is still streaming
 * (`docs/ux/trace.md`'s own testing note: "Open the trace mid-stream and
 * confirm it updates"). Stops the moment the fetched trace itself reports
 * `status !== "running"` — there is nothing left to change after that, and
 * polling a finished turn forever would be a silent, pointless network loop
 * for as long as the panel stays open. */
const POLL_MS = 1000;

/** The toggle under an answer (`docs/ux/trace.md`'s own Entry point) and the
 * panel it opens. One component so the open/closed state and the fetch it
 * drives cannot drift apart — the toggle is the only way in or out.
 *
 * Open/closed state lives on `AskProvider` (`openTraceTurnId`), not as a
 * local `useState`, since `M5-TRACE-FE-121`'s own assumption is that
 * "returning from the viewer restores the trace panel" — a passage clicked
 * inside the panel navigates away to the source viewer, which unmounts this
 * component's own page entirely, and only state held above the router
 * survives that round trip (`ask-state.tsx`'s own `AskApi` doc on
 * `openTraceTurnId`). At most one turn's trace is ever open at a time, which
 * matches this being a full-screen modal panel regardless of how many
 * `TraceToggle`s exist on screen. */
export function TraceToggle({
  turnId,
  messageId,
  running,
}: {
  turnId: string;
  messageId: string | null;
  running: boolean;
}) {
  const { openTraceTurnId, openTrace, closeTrace } = useAsk();
  const control = useRef<HTMLButtonElement>(null);
  const open = openTraceTurnId === turnId;

  const close = (): void => {
    closeTrace();
    // Closing returns to the conversation unchanged (the ticket's own
    // Acceptance Criteria) — including keyboard focus, which otherwise
    // drops to the top of the document.
    control.current?.focus();
  };

  if (messageId === null) return null;

  return (
    <>
      <button
        ref={control}
        type="button"
        onClick={() => {
          recordTraceOpened();
          openTrace(turnId);
        }}
        className="ask-navigates px-2 py-1"
        style={{ border: "1px solid var(--rule)", color: "var(--muted)", fontSize: "var(--t-ui)" }}
        aria-haspopup="dialog"
      >
        How did you get this?
      </button>
      {open ? <TracePanel turnId={turnId} messageId={messageId} running={running} onClose={close} /> : null}
    </>
  );
}

function TracePanel({
  turnId,
  messageId,
  running,
  onClose,
}: {
  turnId: string;
  messageId: string;
  running: boolean;
  onClose: () => void;
}) {
  const { turns } = useAsk();
  const turn = turns.find((candidate) => candidate.id === turnId);
  const citations = turn?.citations ?? [];
  const question = turn?.question ?? "";
  const panel = useRef<HTMLDivElement>(null);
  const [trace, setTrace] = useState<TraceData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async (): Promise<void> => {
      try {
        const data = await fetchTrace(messageId, controller.signal);
        if (stopped) return;
        setTrace(data);
        setError(null);
        // Keep polling only while the turn this trace belongs to is still
        // generating — a completed turn's trace never changes again.
        if (running || data.status === "running") {
          timer = setTimeout(() => void poll(), POLL_MS);
        }
      } catch (thrown) {
        if (stopped) return;
        setError(thrown instanceof Error ? thrown.message : "Askwell could not read that trace.");
      }
    };
    void poll();

    return () => {
      stopped = true;
      controller.abort();
      if (timer !== null) clearTimeout(timer);
    };
    // Restarting on `running`'s own transition to `false` is deliberate,
    // not just tolerated: it fetches the now-final trace immediately
    // rather than waiting up to `POLL_MS` for a poll that was never
    // scheduled to fire again.
  }, [messageId, running]);

  useEffect(() => {
    const first = panel.current?.querySelector<HTMLElement>("button");
    first?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div aria-hidden onClick={onClose} className="fixed inset-0 z-40" style={{ background: "var(--drop)" }} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label="How did you get this?"
        className="fixed top-0 bottom-0 right-0 z-50 flex flex-col overflow-hidden"
        style={{
          width: "min(32rem, 100vw)",
          background: "var(--paper)",
          borderLeft: "1px solid var(--rule-strong)",
          boxShadow: `-2px 0 8px var(--drop)`,
        }}
      >
        <div
          className="flex items-center justify-between px-4 py-3"
          style={{ borderBottom: "1px solid var(--rule)" }}
        >
          <h2 className="ask-prose" style={{ margin: 0 }}>
            How did you get this?
          </h2>
          <div className="flex items-center gap-2">
            {trace !== null ? <CopyTraceButton trace={trace} question={question} /> : null}
            <button
              type="button"
              onClick={onClose}
              className="ask-navigates px-2 py-1"
              style={{ border: "1px solid var(--rule)" }}
            >
              Close
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-3">
          {error !== null ? <p className="ask-prose">{error}</p> : null}
          {trace === null && error === null ? <p className="ask-micro">Loading.</p> : null}
          {trace !== null ? <TraceBody trace={trace} turnId={turnId} citations={citations} /> : null}
        </div>
      </div>
    </>
  );
}

/** "Copy trace" (`docs/ux/trace.md` §4, this ticket's own Scope) — plain
 * text, via `buildTraceCopyText`, with the same copy-then-flash-"Copied"
 * feedback `context-rail.tsx`'s `CopyPassage` already established for a
 * clipboard action in this app. */
function CopyTraceButton({ trace, question }: { trace: TraceData; question: string }) {
  const [copied, setCopied] = useState(false);

  const copy = (): void => {
    void navigator.clipboard.writeText(buildTraceCopyText(trace, question)).then(() => {
      recordTraceCopy();
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <button
      type="button"
      onClick={copy}
      className="ask-navigates px-2 py-1"
      style={{ border: "1px solid var(--rule)" }}
    >
      {copied ? "Copied" : "Copy trace"}
    </button>
  );
}

function TraceBody({
  trace,
  turnId,
  citations,
}: {
  trace: TraceData;
  turnId: string;
  citations: CitationCard[];
}) {
  // `docs/ux/trace.md` §5: traces are a capped ring buffer — an old one is
  // gone, and the important records (the answer and its sources) survive
  // regardless. This state takes priority over an empty step list, which
  // otherwise reads identically to a turn genuinely rotated.
  if (trace.trace_rotated) {
    return (
      <p className="ask-prose">
        The detailed trace for this answer has been cleared. The answer and its sources are still
        in your log.
      </p>
    );
  }

  const rows = traceRows(trace.steps);
  const pendingCalls = toolCeilingPendingCalls(trace);

  return (
    <div className="flex flex-col gap-3">
      <BackendLine trace={trace} />
      {rows.length === 0 ? (
        <p className="ask-prose">Nothing was recorded for this turn yet.</p>
      ) : (
        <ol className="flex flex-col gap-3" style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {rows.map((row) => (
            <TraceStepRow key={row.index} row={row} turnId={turnId} citations={citations} />
          ))}
          {trace.steps_truncated ? (
            <li className="ask-micro">Some steps from this turn were left out to keep the trace short.</li>
          ) : null}
        </ol>
      )}
      {pendingCalls !== null ? <ToolCeilingNote pendingCalls={pendingCalls} /> : null}
    </div>
  );
}

/** Backend and model, named once per turn (`docs/ux/trace.md` §3's own
 * "Backend" row) — never per step, since one turn has exactly one. Absent
 * rather than a placeholder when the stored trace predates this field. */
function BackendLine({ trace }: { trace: TraceData }) {
  if (trace.backend === undefined) return null;
  return (
    <p className="ask-micro" style={{ textTransform: "none" }}>
      {trace.backend.mode} · {trace.backend.model}
    </p>
  );
}

/** The tool-ceiling stop (`docs/ux/trace.md` §3, `M5-LOOP-BE-116`) — what
 * the turn was about to do when the 8-call budget ran out. Informational,
 * not an error: the turn still answered with what it had. */
function ToolCeilingNote({ pendingCalls }: { pendingCalls: PendingToolCall[] }) {
  return (
    <div className="flex flex-col gap-1" style={{ borderTop: "1px solid var(--rule)", paddingTop: "0.5rem" }}>
      <p className="ask-prose" style={{ margin: 0 }}>
        Stopped after 8 steps for this question.
      </p>
      {pendingCalls.length > 0 ? (
        <ul className="ask-micro" style={{ textTransform: "none", margin: 0, paddingLeft: "1rem" }}>
          {pendingCalls.map((call, index) => (
            <li key={index}>
              About to call {call.tool}
              {Object.keys(call.arguments).length > 0
                ? ` (${JSON.stringify(call.arguments)})`
                : ""}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function TraceStepRow({
  row,
  turnId,
  citations,
}: {
  row: TraceRow;
  turnId: string;
  citations: CitationCard[];
}) {
  return (
    <li className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-3">
        <span className="ask-prose" style={{ margin: 0 }}>
          {row.index}&nbsp;&nbsp;{row.summary}
        </span>
        {/* Timings are always visible, never behind the expander below
            (the ticket's own Validation Rule) — a step with no timing at
            all (e.g. `memory_retrieve`) simply shows none, rather than a
            fabricated one. */}
        {row.duration !== null ? (
          <span className="ask-micro" style={{ whiteSpace: "nowrap" }}>
            {row.duration}
          </span>
        ) : null}
      </div>
      {row.expandable ? (
        <details>
          <summary className="ask-micro" style={{ cursor: "pointer" }}>
            show detail
          </summary>
          <div style={{ marginTop: "0.25rem" }}>
            <StepDetail step={row.step} turnId={turnId} citations={citations} />
          </div>
        </details>
      ) : null}
    </li>
  );
}

/** What is inside a step's raw detail, formatted for the item it is
 * (`docs/ux/trace.md` §3) rather than the raw JSON `M5-TRACE-FE-119` left
 * here. A kind this module does not specifically know how to render falls
 * back to the raw dump — the same "never a blank row" rule `stepSummary`
 * already follows for an unfamiliar `kind`. */
function StepDetail({
  step,
  turnId,
  citations,
}: {
  step: TraceStep;
  turnId: string;
  citations: CitationCard[];
}) {
  if (step.kind === "retrieve") return <RetrieveStepDetail step={step} turnId={turnId} citations={citations} />;
  if (step.kind === "memory_retrieve") return <MemoryRetrieveStepDetail step={step} />;
  const sql = sqlStepInfo(step);
  if (sql !== null) return <SqlStepDetail sql={sql} />;
  if (step.kind === "tool") return <ToolStepDetail step={step} />;
  return <RawStepDetail step={step} />;
}

function RawStepDetail({ step }: { step: TraceStep }) {
  return (
    <pre
      className="ask-micro"
      style={{ textTransform: "none", whiteSpace: "pre-wrap", wordBreak: "break-word" }}
    >
      {JSON.stringify(step, null, 2)}
    </pre>
  );
}

/** Every candidate with its score and the threshold beside it
 * (`docs/ux/trace.md` §3's Validation Rule) — the only way a near-miss
 * abstention ("the right passage at 0.61 under a 0.65 threshold") reads as
 * explained rather than broken. Sorted highest first so the near-miss is
 * the first thing shown, not something to scan for. A score at or above
 * the threshold is what actually cleared it (`--provenance`); below is
 * shown the same way an unconfirmed value is (`--muted`), matching
 * `design-system.md` §2 rather than inventing a third colour.
 *
 * `M5-TRACE-FE-121` adds full passage text and a click-through, but only
 * for a hit that matches one of the answer's own citation cards
 * (`hitCitation`) — the raw `{chunk_id, score}` pair a retrieval candidate
 * carries has no filename or passage text of its own, and a candidate the
 * answer never actually cited (a near-miss, or one outscored for its own
 * claim) has nowhere for a click to go. */
function RetrieveStepDetail({
  step,
  turnId,
  citations,
}: {
  step: TraceStep;
  turnId: string;
  citations: CitationCard[];
}) {
  const threshold = retrievalThreshold(step);
  const hits = retrievedHits(step);
  return (
    <div className="flex flex-col gap-1">
      {threshold !== null ? (
        <p className="ask-micro" style={{ textTransform: "none" }}>
          Threshold {threshold.toFixed(2)}
        </p>
      ) : null}
      {hits.length === 0 ? (
        <p className="ask-micro" style={{ textTransform: "none" }}>
          Nothing came back.
        </p>
      ) : (
        <ul className="flex flex-col gap-1" style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {hits.map((hit) => (
            <PassageRow
              key={hit.chunkId}
              hit={hit}
              threshold={threshold}
              card={hitCitation(hit, citations)}
              turnId={turnId}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function PassageRow({
  hit,
  threshold,
  card,
  turnId,
}: {
  hit: RetrievedHit;
  threshold: number | null;
  card: CitationCard | null;
  turnId: string;
}) {
  const scoreColor = threshold !== null && hit.score >= threshold ? "var(--provenance)" : "var(--muted)";
  // Not cited in the answer at all — nothing but the score to show, same as
  // before this ticket.
  if (card === null) {
    return (
      <li className="ask-micro" style={{ textTransform: "none", color: scoreColor }}>
        {hit.score.toFixed(2)}
      </li>
    );
  }
  return <CitedPassageRow hit={hit} scoreColor={scoreColor} card={card} turnId={turnId} />;
}

/** A retrieved hit the answer actually cited: full passage text, and a
 * click-through to the source viewer at that position (this ticket's own
 * Scope) — unless the document it came from has since been deleted, in
 * which case it renders the same way a deleted source already does in the
 * answer's own cards (`useDeletion`, `provenance-margin.tsx`): greyed, not
 * clickable (the ticket's own Edge Case). `card.claimOrdinals[0]` is enough
 * for the viewer's "back to answer" origin — a citation card always has at
 * least one claim, and the trace itself does not know which one sent
 * someone looking at this particular candidate. */
function CitedPassageRow({
  hit,
  scoreColor,
  card,
  turnId,
}: {
  hit: RetrievedHit;
  scoreColor: string;
  card: CitationCard;
  turnId: string;
}) {
  const deletion = useDeletion(card.documentId);
  const label = pageLabel(card);
  return (
    <li className="flex flex-col gap-0.5">
      <span className="ask-micro" style={{ textTransform: "none", color: scoreColor }}>
        {hit.score.toFixed(2)} · {card.filename}
        {label !== null ? ` · ${label}` : ""}
        {deletion.deleted ? " · deleted" : ""}
      </span>
      {deletion.deleted ? (
        <span className="ask-prose" style={{ color: "var(--muted)" }}>
          {card.passage}
        </span>
      ) : (
        <Link
          href={documentHref(card, { turnId, claimOrdinal: card.claimOrdinals[0]! })}
          className="ask-navigates ask-prose"
        >
          {card.passage}
        </Link>
      )}
    </li>
  );
}

/** Memory facts and schema notes used by this turn, with their origin
 * markers (`docs/ux/trace.md` §3's "Memory facts used", the Edge Case "a
 * turn using memory heavily — facts listed with their origin markers"). The
 * step itself carries only ids (`askwell.ask`'s `memory_fact_ids`/
 * `schema_note_ids`) — this fetches each one's current subject/value/origin
 * the same way a chip's popover already does
 * (`lib/memory-chips.ts::fetchFactDetail`), rather than a second read path.
 *
 * `data-supplied={origin !== "inferred"}`, not `=== "user"` — a memory
 * fact's own origins are `clarification`/`correction`/`manual`/`inferred`
 * (`MEMORY_ORIGINS`), never literally `"user"`; only a schema note's are.
 * `!== "inferred"` is the check every other marker in this codebase already
 * uses (`ask-screen.tsx`, `memory-screen.tsx`) — tracker issue 428.
 *
 * `M5-TRACE-FE-121`: each fact renders as the same `MemoryChip` an answer's
 * own claim uses — "clicking a memory fact opens the same popover as in an
 * answer, with correct and delete" is only true reusing that component, not
 * a lookalike. `claimOrdinal: 0` is a placeholder the popover never reads
 * (`MemoryFactPopover` only ever uses `chip.factKind`/`chip.factId`/
 * `chip.fact` as an initial-load fallback); nothing here has an actual claim
 * to attach to, since a trace's retrieval step is not scoped to one claim
 * the way an answer's own citation is.
 */
function MemoryRetrieveStepDetail({ step }: { step: TraceStep }) {
  const refs = memoryFactRefs(step);
  const [details, setDetails] = useState<Record<string, FactDetail | null>>({});

  useEffect(() => {
    let cancelled = false;
    void Promise.all(
      refs.map(async (ref) => {
        try {
          const detail = await fetchFactDetail(ref.factKind, ref.factId);
          return [refKey(ref), detail] as const;
        } catch {
          return [refKey(ref), null] as const;
        }
      }),
    ).then((entries) => {
      if (!cancelled) setDetails(Object.fromEntries(entries));
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `refs` is derived fresh from `step` every render
  }, [step]);

  if (refs.length === 0) return null;

  return (
    <ul className="flex flex-col gap-1" style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {refs.map((ref) => {
        const fact = details[refKey(ref)];
        return (
          <li key={refKey(ref)} className="flex items-center gap-2">
            {fact === undefined ? (
              <span className="ask-micro" style={{ textTransform: "none" }}>
                Loading…
              </span>
            ) : fact === null ? (
              <span className="ask-micro" style={{ textTransform: "none" }}>
                This fact is no longer available.
              </span>
            ) : (
              <MemoryChip
                chip={{
                  claimOrdinal: 0,
                  factKind: ref.factKind,
                  factId: ref.factId,
                  subject: fact.subject,
                  fact: fact.value,
                  origin: fact.origin,
                  confidence: null,
                  suppliedAt: fact.createdAt,
                }}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
}

function refKey(ref: MemoryFactRef): string {
  return `${ref.factKind}:${ref.factId}`;
}

/** A database turn — the generated query, whether validation accepted it,
 * and the injected `LIMIT` (`docs/ux/trace.md` §3). Rejected SQL is shown,
 * not hidden: "the signal that generation has degraded" is invisible
 * unless surfaced here (`../audit-log.md` §7, this ticket's own Detailed
 * Description). `QueryDisclosure` is the same component a completed
 * database answer already renders the query with — its `LIMIT ... /*
 * Added by Askwell *\/` highlighting is what makes the injected limit
 * visible without a second field to keep in sync. */
function SqlStepDetail({ sql }: { sql: ReturnType<typeof sqlStepInfo> }) {
  if (sql === null) return null;
  const failed = sql.outcome !== "ok" && sql.outcome !== "executed";
  return (
    <div className="flex flex-col gap-1">
      <p className="ask-micro" style={{ textTransform: "none" }}>
        {sql.outcome}
        {sql.rows !== null ? ` — ${sql.rows} row${sql.rows === 1 ? "" : "s"}` : ""}
        {sql.truncated === true ? ", truncated" : ""}
      </p>
      {failed && sql.reason !== null ? (
        // Rendered fully, never truncated — the ticket's own edge case
        // ("a rejected query with a long reason") and the reason this
        // whole step exists to show.
        <p className="ask-micro" style={{ textTransform: "none", whiteSpace: "pre-wrap" }}>
          Reason: {sql.reason}
        </p>
      ) : null}
      {sql.query !== null ? <QueryDisclosure query={sql.query} /> : null}
    </div>
  );
}

/** A tool call's own arguments and, when C7 flagged it, the patterns found
 * (`docs/ux/trace.md` §3's "Injection flags" — "flagged here, per step for
 * a tool call, not as an alarm in the answer"). Rendered as information: no
 * warning colour, no icon, `--muted` text like any other metadata. */
function ToolStepDetail({ step }: { step: TraceStep }) {
  const patterns = toolInjectionPatterns(step);
  const args =
    step.arguments && typeof step.arguments === "object"
      ? (step.arguments as Record<string, unknown>)
      : {};
  return (
    <div className="flex flex-col gap-1">
      {Object.keys(args).length > 0 ? (
        <pre
          className="ask-micro"
          style={{ textTransform: "none", whiteSpace: "pre-wrap", wordBreak: "break-word", margin: 0 }}
        >
          {JSON.stringify(args, null, 2)}
        </pre>
      ) : null}
      {patterns !== null ? (
        <p className="ask-micro" style={{ textTransform: "none", color: "var(--muted)" }}>
          May contain instruction-like text
          {patterns.length > 0 ? `: ${patterns.join(", ")}` : ""}
        </p>
      ) : null}
    </div>
  );
}
