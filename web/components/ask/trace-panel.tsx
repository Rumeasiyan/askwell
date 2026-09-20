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

import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchTrace,
  recordTraceOpened,
  traceRows,
  type TraceData,
  type TraceRow,
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
 * drives cannot drift apart — the toggle is the only way in or out. */
export function TraceToggle({ messageId, running }: { messageId: string | null; running: boolean }) {
  const [open, setOpen] = useState(false);
  const control = useRef<HTMLButtonElement>(null);

  const close = useCallback(() => {
    setOpen(false);
    // Closing returns to the conversation unchanged (the ticket's own
    // Acceptance Criteria) — including keyboard focus, which otherwise
    // drops to the top of the document.
    control.current?.focus();
  }, []);

  if (messageId === null) return null;

  return (
    <>
      <button
        ref={control}
        type="button"
        onClick={() => {
          recordTraceOpened();
          setOpen(true);
        }}
        className="ask-navigates px-2 py-1"
        style={{ border: "1px solid var(--rule)", color: "var(--muted)", fontSize: "var(--t-ui)" }}
        aria-haspopup="dialog"
      >
        How did you get this?
      </button>
      {open ? <TracePanel messageId={messageId} running={running} onClose={close} /> : null}
    </>
  );
}

function TracePanel({
  messageId,
  running,
  onClose,
}: {
  messageId: string;
  running: boolean;
  onClose: () => void;
}) {
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
          <button
            type="button"
            onClick={onClose}
            className="ask-navigates px-2 py-1"
            style={{ border: "1px solid var(--rule)" }}
          >
            Close
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-3">
          {error !== null ? <p className="ask-prose">{error}</p> : null}
          {trace === null && error === null ? <p className="ask-micro">Loading.</p> : null}
          {trace !== null ? <TraceBody trace={trace} /> : null}
        </div>
      </div>
    </>
  );
}

function TraceBody({ trace }: { trace: TraceData }) {
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
  if (rows.length === 0) {
    return <p className="ask-prose">Nothing was recorded for this turn yet.</p>;
  }

  return (
    <ol className="flex flex-col gap-3" style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {rows.map((row) => (
        <TraceStepRow key={row.index} row={row} />
      ))}
      {trace.steps_truncated ? (
        <li className="ask-micro">Some steps from this turn were left out to keep the trace short.</li>
      ) : null}
    </ol>
  );
}

function TraceStepRow({ row }: { row: TraceRow }) {
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
          <pre
            className="ask-micro"
            style={{
              textTransform: "none",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              marginTop: "0.25rem",
            }}
          >
            {JSON.stringify(row.step, null, 2)}
          </pre>
        </details>
      ) : null}
    </li>
  );
}
