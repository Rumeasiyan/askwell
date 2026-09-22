"use client";

/**
 * Verify the log — `docs/ux/settings.md` §6, `M7-LOG-FE-156`.
 *
 * One action, two reports (one per store, `docs/audit-log.md` §2's own
 * reason the stores are separate). `GET /log-verify` answers once rather
 * than through a poll loop — see `lib/verify.ts` for why there is no job
 * here the way export and prune have one.
 *
 * "Interruptible" for a read that changes nothing is the request itself:
 * navigating away, or pressing Stop, aborts the fetch via `AbortController`.
 * Nothing was written by starting the check, so there is nothing to undo by
 * stopping it. "Progress" for a walk with no natural midpoint to report is
 * an elapsed-time counter plus the two stores resolving independently as
 * each finishes, rather than a fabricated percentage.
 *
 * The word "immutable" must never appear here — `docs/decisions.md` and
 * `docs/audit-log.md` §4 are explicit that the guarantee is tamper-evidence,
 * not tamper-proofing, and the wrong word here is the wrong promise.
 */

import { useEffect, useRef, useState } from "react";

import { verifyLog, type StoreVerification, type VerificationReport } from "@/lib/verify";

type RunState = "idle" | "checking" | "done" | "error";

export function VerifyLog() {
  const [state, setState] = useState<RunState>("idle");
  const [report, setReport] = useState<VerificationReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (state !== "checking") {
      return;
    }
    const started = Date.now();
    const interval = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [state]);

  useEffect(() => {
    return () => controllerRef.current?.abort();
  }, []);

  const start = (): void => {
    const controller = new AbortController();
    controllerRef.current = controller;
    setState("checking");
    setError(null);
    setReport(null);
    setElapsedSeconds(0);
    verifyLog(controller.signal)
      .then((result) => {
        setReport(result);
        setState("done");
      })
      .catch((thrown: unknown) => {
        if (controller.signal.aborted) {
          setState("idle");
          return;
        }
        setError(thrown instanceof Error ? thrown.message : "Askwell could not verify the log.");
        setState("error");
      });
  };

  const stop = (): void => {
    controllerRef.current?.abort();
  };

  return (
    <div className="flex flex-col gap-2">
      <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>Verify the log</h3>
      <p className="ask-micro" style={{ textTransform: "none" }}>
        Walks the hash chain in both audit stores and reports whether each is intact. Askwell
        never rewrites or deletes a record after it is written — no code path here has
        permission to. A break means something outside Askwell changed the file. This is
        tamper-evident, not tamper-proof: the guarantee is that tampering can be detected, not
        that it can be prevented.
      </p>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={start}
          disabled={state === "checking"}
          className="ask-navigates px-2 py-1"
          style={{ border: "1px solid var(--rule)" }}
        >
          {state === "checking" ? "Checking…" : "Verify the log"}
        </button>
        {state === "checking" ? (
          <>
            <span className="ask-micro" role="status" style={{ color: "var(--muted)" }}>
              Checking… {elapsedSeconds}s
            </span>
            <button
              type="button"
              onClick={stop}
              className="ask-navigates px-2 py-1"
              style={{ border: "1px solid var(--rule)" }}
            >
              Stop
            </button>
          </>
        ) : null}
      </div>

      {error !== null ? (
        <p className="ask-micro" style={{ textTransform: "none", color: "var(--alarm)" }}>
          {error}
        </p>
      ) : null}

      {report !== null ? (
        <div className="flex flex-col gap-3">
          <StoreReport label="Decisions" result={report.decisions} />
          <StoreReport label="Interactions" result={report.interactions} />
        </div>
      ) : null}
    </div>
  );
}

function StoreReport({ label, result }: { label: string; result: StoreVerification }) {
  const brokenDate =
    result.broken_at !== null ? new Date(result.broken_at).toLocaleDateString() : null;

  return (
    <div
      role="status"
      className="ask-carries-meaning px-4 py-3"
      style={{
        background: "var(--surface)",
        borderLeftColor: result.intact ? "var(--provenance)" : "var(--alarm)",
        borderRadius: "var(--radius)",
      }}
    >
      <p className="ask-micro" style={{ color: result.intact ? "var(--provenance)" : "var(--alarm)" }}>
        {label} — {result.intact ? "chain intact" : "chain broken"}
      </p>
      <p className="mt-1" style={{ fontSize: "var(--t-meta)", lineHeight: "var(--t-meta-lh)" }}>
        {result.intact
          ? `${result.checked} records checked.`
          : `Breaks at record ${result.broken_record_id ?? "unknown"}${
              brokenDate !== null ? ` (${brokenDate})` : ""
            }. ${result.detail}`}
      </p>
      {result.intact && result.note !== "" ? (
        <p className="mt-1 ask-micro" style={{ textTransform: "none", color: "var(--muted)" }}>
          {result.note}
        </p>
      ) : null}
    </div>
  );
}
