"use client";

/**
 * The settings screen's "Verify the log" action — `docs/ux/settings.md`
 * §6/§8, ticket `M7-LOG-FE-156`. One action and two reports: intact, or
 * broken naming the record and its date, with the explanation that Askwell
 * never rewrites history so a break means something outside it changed the
 * file. The word "immutable" never appears — C6, `docs/audit-log.md` §4.
 */

import { useEffect, useRef, useState } from "react";

import {
  cancelVerify,
  createVerify,
  fetchVerify,
  isFinished,
  type StoreOutcome,
  type VerifyJob,
} from "@/lib/log-verify";

/** Re-polled while a job runs, the same cadence `trace-panel.tsx`'s own
 * `POLL_MS` uses for the same reason: stop the moment the job itself
 * reports it is no longer running. */
const POLL_MS = 1000;

const STORE_LABEL: Record<"decisions" | "interactions", string> = {
  decisions: "Decisions",
  interactions: "Interactions",
};

export function VerifyLog() {
  const [job, setJob] = useState<VerifyJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = (): void => {
    if (timer.current !== null) {
      clearInterval(timer.current);
      timer.current = null;
    }
  };

  useEffect(() => stopPolling, []);

  const poll = (jobId: string): void => {
    stopPolling();
    timer.current = setInterval(() => {
      void fetchVerify(jobId)
        .then((updated) => {
          setJob(updated);
          if (isFinished(updated)) stopPolling();
        })
        .catch((thrown: unknown) => {
          stopPolling();
          setError(thrown instanceof Error ? thrown.message : "Askwell lost track of the verification.");
        });
    }, POLL_MS);
  };

  const start = (): void => {
    setError(null);
    setJob(null);
    void createVerify()
      .then((created) => {
        setJob(created);
        if (!isFinished(created)) poll(created.id);
      })
      .catch((thrown: unknown) => {
        setError(thrown instanceof Error ? thrown.message : "Askwell could not start verification.");
      });
  };

  const cancel = (): void => {
    if (job === null) return;
    setCancelling(true);
    void cancelVerify(job.id)
      .then((updated) => {
        setJob(updated);
        if (isFinished(updated)) stopPolling();
      })
      .catch((thrown: unknown) => {
        setError(thrown instanceof Error ? thrown.message : "Askwell could not cancel the verification.");
      })
      .finally(() => setCancelling(false));
  };

  const running = job !== null && !isFinished(job);

  return (
    <div className="flex flex-col gap-2">
      <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>Verify the log</h3>
      <p className="ask-micro" style={{ textTransform: "none" }}>
        Checks both stores&apos; hash chains and reports where, if anywhere, one breaks. Askwell
        never rewrites history — it has no permission to. A break means something outside Askwell
        changed the file.
      </p>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={start}
          disabled={running}
          className="ask-navigates px-2 py-1"
          style={{ border: "1px solid var(--rule)" }}
        >
          {running ? "Verifying…" : "Verify the log"}
        </button>
        {running ? (
          <button
            type="button"
            onClick={cancel}
            disabled={cancelling}
            className="px-2 py-1"
            style={{ border: "1px solid var(--rule)", color: "var(--muted)" }}
          >
            {cancelling ? "Stopping…" : "Stop"}
          </button>
        ) : null}
      </div>

      {running ? (
        <p role="status" className="ask-micro" style={{ textTransform: "none" }}>
          Checked {job.decisions.checked + job.interactions.checked} of{" "}
          {job.decisions.total + job.interactions.total} records…
        </p>
      ) : null}

      {job !== null && job.status === "cancelled" ? (
        <p className="ask-micro" style={{ textTransform: "none", color: "var(--muted)" }}>
          Stopped before finishing. Nothing was found broken or confirmed intact — run it again to
          get a result.
        </p>
      ) : null}

      {job !== null && job.status === "failed" ? (
        <p className="ask-micro" style={{ textTransform: "none", color: "var(--alarm)" }}>
          {job.error ?? "Verification failed for an unknown reason."}
        </p>
      ) : null}

      {job !== null && job.status === "done" ? (
        <div className="flex flex-col gap-2">
          <StoreReport label={STORE_LABEL.decisions} outcome={job.decisions} />
          <StoreReport label={STORE_LABEL.interactions} outcome={job.interactions} />
        </div>
      ) : null}

      {error !== null ? (
        <p className="ask-micro" style={{ textTransform: "none", color: "var(--alarm)" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

function StoreReport({ label, outcome }: { label: string; outcome: StoreOutcome }) {
  if (outcome.intact === null) {
    // Nothing to check — an empty store (no interactions yet, for instance)
    // verifies vacuously true in `askwell.audit.verify`, but `intact` is
    // only ever `null` here if this store's own walk never completed.
    return null;
  }

  if (outcome.intact) {
    return (
      <p className="ask-micro" style={{ textTransform: "none", color: "var(--provenance)" }}>
        {label}: {outcome.checked} records, chain intact.
      </p>
    );
  }

  const when = outcome.break_at
    ? new Date(outcome.break_at).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "an unknown date";

  return (
    <div
      role="status"
      className="ask-carries-meaning px-4 py-3"
      style={{
        background: "var(--surface)",
        borderLeftColor: "var(--alarm)",
        borderRadius: "var(--radius)",
      }}
    >
      <p className="ask-micro" style={{ color: "var(--alarm)" }}>
        {label}: chain breaks
      </p>
      <p className="mt-1" style={{ fontSize: "var(--t-meta)", lineHeight: "var(--t-meta-lh)" }}>
        {outcome.break_id !== null
          ? `At the record written ${when} (${outcome.break_id}).`
          : `No single record to name — the first record itself has been removed.`}{" "}
        {outcome.break_detail}
      </p>
      {outcome.break_reason === "forked" ? null : (
        <p className="mt-1" style={{ fontSize: "var(--t-meta)", lineHeight: "var(--t-meta-lh)" }}>
          Askwell never rewrites history — it has no permission to. This means something outside
          Askwell changed the file after it was written.
        </p>
      )}
    </div>
  );
}
