"use client";

import { useEffect, useState } from "react";

import {
  type ReapplyJob,
  fetchReapplyJob,
  reapplyFailureReason,
  retryReapplyJob,
} from "@/lib/clarifications";

const POLL_INTERVAL_MS = 2000;

/**
 * `../ux/clarifications.md` §5, "Answered, re-processing" — per-item
 * progress while the source stays queryable. Polled, not pushed: there is no
 * SSE stream for `reapply_jobs` the way `askwell.ingest` has one.
 *
 * A failure is surfaced with its own reason and a retry, never a stuck
 * indicator (issue 299, the ticket's own named Edge Case).
 */
export function ReapplyProgress({
  jobId,
  subject,
  onDone,
}: {
  jobId: string;
  subject: string;
  onDone: () => void;
}) {
  const [job, setJob] = useState<ReapplyJob | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [pollKey, setPollKey] = useState(0);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = () => {
      fetchReapplyJob(jobId)
        .then((next) => {
          if (!live) return;
          setJob(next);
          if (next.status === "done") {
            onDone();
            return;
          }
          if (next.status === "queued" || next.status === "running") {
            timer = setTimeout(poll, POLL_INTERVAL_MS);
          }
        })
        .catch((error: unknown) => {
          if (live) setFailure(String(error));
        });
    };
    poll();

    return () => {
      live = false;
      if (timer !== null) clearTimeout(timer);
    };
    // `pollKey` is the retry button's own way of restarting this loop —
    // `onDone` is intentionally left out, since it is stable per mount and
    // including it would re-subscribe on every parent re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, pollKey]);

  const handleRetry = () => {
    setRetrying(true);
    retryReapplyJob(jobId)
      .then(() => setPollKey((key) => key + 1))
      .catch((error: unknown) => setFailure(String(error)))
      .finally(() => setRetrying(false));
  };

  if (failure !== null) {
    return (
      <p className="ask-micro" style={{ color: "var(--alarm)" }}>
        Askwell lost track of re-reading {subject}: {failure}
      </p>
    );
  }

  if (job === null) {
    return (
      <p className="ask-micro" style={{ color: "var(--muted)" }}>
        Re-reading {subject}…
      </p>
    );
  }

  const reason = reapplyFailureReason(job);

  return (
    <div
      className="flex flex-col gap-1 px-4 py-3"
      style={{ background: "var(--surface)", borderRadius: "var(--radius)" }}
    >
      <div className="flex items-baseline justify-between gap-3">
        <p className="ask-prose">
          Re-reading {subject} — {job.done_items} of {job.total_items} done. The source stays searchable.
        </p>
      </div>
      {job.status === "failed" ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="ask-micro" style={{ color: "var(--alarm)" }}>
            Stopped, not stuck: {reason ?? "an unknown error."}
          </p>
          <button
            type="button"
            className="ask-navigates ask-micro"
            onClick={handleRetry}
            disabled={retrying}
          >
            Retry
          </button>
        </div>
      ) : null}
    </div>
  );
}
