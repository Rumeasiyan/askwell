"use client";

/**
 * Your data — `docs/ux/settings.md` §6, `M7-DATA-FE-160`. The section that
 * proves the product means what it says: export everything, export the log
 * alone, delete a source, delete all memory, reset, and verify the log.
 *
 * Each action is independent — its own fetch, its own error — so one
 * failing never takes the others with it. Deleting a single source stays on
 * the Library screen (`docs/ux/library.md` §4), where the source is, and is
 * reached from here by link rather than rebuilt. Verification is
 * `M7-LOG-FE-156`'s `VerifyLog`, placed here unchanged.
 *
 * Every destructive confirmation names the count and says it cannot be
 * undone. Reset says, before anything else, that the user's own files are
 * never touched — the thing a person handing on a laptop fears most.
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { VerifyLog } from "@/components/settings/verify-log";
import {
  EXPORT_CONTENTS,
  UNPROTECTED_EXPORT_WARNING,
  exportDownloadUrl,
  exportFinished,
  exportProgress,
  fetchExportJob,
  startExport,
  type ExportJob,
  type ExportScope,
} from "@/lib/data-export";
import { deleteAllConfirmationCopy, deleteAllMemory, fetchMemoryScreen } from "@/lib/memory";
import { formatBytes } from "@/lib/model";
import { fetchPassphraseStatus } from "@/lib/passphrase";
import {
  RESET_IRREVERSIBLE,
  RESET_LOG_STATEMENT,
  fetchResetPreview,
  performReset,
  resetDestroys,
  resetOutcome,
  type ResetPreview,
  type ResetResult,
} from "@/lib/reset";

const POLL_MS = 1000;

const heading = { fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" } as const;
const micro = { textTransform: "none" } as const;
const outlined = { border: "1px solid var(--rule)" } as const;
const panel = { background: "var(--surface)", borderRadius: "var(--radius)" } as const;

export function YourData() {
  return (
    <section className="flex flex-col gap-6">
      <h2 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>Your data</h2>
      <ExportAction scope="everything" title="Export everything" />
      <ExportAction scope="log" title="Export the log" />
      <DeleteSource />
      <DeleteAllMemory />
      <VerifyLog />
      <ResetAskwell />
    </section>
  );
}

function ErrorLine({ message }: { message: string | null }) {
  if (message === null) return null;
  return (
    <p className="ask-micro" role="alert" style={{ ...micro, color: "var(--alarm)" }}>
      {message}
    </p>
  );
}

// --- export -------------------------------------------------------------

type ExportState = "idle" | "checking" | "warning" | "starting" | "running" | "done" | "failed";

function ExportAction({ scope, title }: { scope: ExportScope; title: string }) {
  const [state, setState] = useState<ExportState>("idle");
  const [job, setJob] = useState<ExportJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const poll = (id: string): void => {
    const controller = new AbortController();
    controllerRef.current = controller;
    const tick = (): void => {
      fetchExportJob(id, controller.signal)
        .then((current) => {
          setJob(current);
          if (!exportFinished(current)) {
            setTimeout(tick, POLL_MS);
            return;
          }
          setState(current.status === "done" ? "done" : "failed");
        })
        .catch((thrown: unknown) => {
          if (controller.signal.aborted) return;
          setError(thrown instanceof Error ? thrown.message : "Askwell could not read the export.");
          setState("failed");
        });
    };
    tick();
  };

  const write = (acknowledged: boolean): void => {
    setState("starting");
    startExport(scope, acknowledged)
      .then((started) => {
        setJob(started);
        setState("running");
        poll(started.id);
      })
      .catch((thrown: unknown) => {
        setError(thrown instanceof Error ? thrown.message : "Askwell could not start the export.");
        setState("failed");
      });
  };

  // The passphrase warning comes before anything is written, never after.
  const begin = (): void => {
    setError(null);
    setJob(null);
    setState("checking");
    fetchPassphraseStatus()
      .then((status) => {
        if (status.enabled) {
          setState("warning");
          return;
        }
        write(false);
      })
      .catch((thrown: unknown) => {
        setError(thrown instanceof Error ? thrown.message : "Askwell could not start the export.");
        setState("failed");
      });
  };

  const busy = state === "checking" || state === "starting" || state === "running";

  return (
    <div className="flex flex-col gap-2">
      <h3 style={heading}>{title}</h3>
      <p className="ask-micro" style={micro}>
        {EXPORT_CONTENTS[scope]}
      </p>

      {state === "warning" ? (
        <div className="flex flex-col gap-2 px-4 py-3" style={panel}>
          <p className="ask-prose" style={{ color: "var(--alarm)" }}>
            {UNPROTECTED_EXPORT_WARNING}
          </p>
          <div className="flex gap-2">
            <button type="button" className="ask-action-primary px-3 py-1" onClick={() => write(true)}>
              Export without protection
            </button>
            <button
              type="button"
              className="ask-navigates px-3 py-1"
              style={outlined}
              onClick={() => setState("idle")}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="ask-navigates px-2 py-1"
            style={outlined}
            onClick={begin}
            disabled={busy}
          >
            {busy ? "Exporting…" : title}
          </button>
        </div>
      )}

      {state === "running" && job !== null ? (
        <p className="ask-micro" role="status" style={{ ...micro, color: "var(--muted)" }}>
          {exportProgress(job)} This runs in the background; you can keep using Askwell.
        </p>
      ) : null}

      {state === "done" && job !== null ? (
        <p className="ask-micro" role="status" style={micro}>
          Ready{job.file_bytes !== null ? `, ${formatBytes(job.file_bytes)}` : ""}.{" "}
          <a href={exportDownloadUrl(job.id)} download className="ask-navigates">
            Download the export
          </a>
        </p>
      ) : null}

      {state === "failed" && job?.error ? <ErrorLine message={`The export failed: ${job.error}`} /> : null}
      <ErrorLine message={error} />
    </div>
  );
}

// --- delete a source ----------------------------------------------------

function DeleteSource() {
  return (
    <div className="flex flex-col gap-2">
      <h3 style={heading}>Delete a source</h3>
      <p className="ask-micro" style={micro}>
        One source at a time, from the Library. The file on your disk is untouched; Askwell
        forgets its contents, and past answers that cited it show it as deleted.{" "}
        <Link href="/library" className="ask-navigates">
          Open the Library
        </Link>
      </p>
    </div>
  );
}

// --- delete all memory --------------------------------------------------

type MemoryState = "idle" | "counting" | "confirming" | "deleting" | "deleted";

function DeleteAllMemory() {
  const [state, setState] = useState<MemoryState>("idle");
  const [count, setCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const start = (): void => {
    setError(null);
    setState("counting");
    fetchMemoryScreen()
      .then((screen) => {
        setCount(screen.rows.length);
        setState("confirming");
      })
      .catch((thrown: unknown) => {
        setError(thrown instanceof Error ? thrown.message : "Askwell could not count memory.");
        setState("idle");
      });
  };

  const confirm = (): void => {
    setState("deleting");
    deleteAllMemory(count)
      .then(() => setState("deleted"))
      .catch((thrown: unknown) => {
        // A 409 means memory changed after the count was shown: count again
        // rather than delete a set the user never saw.
        setError(thrown instanceof Error ? thrown.message : "That deletion failed.");
        setState("idle");
      });
  };

  return (
    <div className="flex flex-col gap-2">
      <h3 style={heading}>Delete all memory</h3>
      <p className="ask-micro" style={micro}>
        Every fact Askwell has learned or been told, including what columns in your databases
        mean. Your sources and conversations stay.
      </p>

      {state === "confirming" && count === 0 ? (
        <p className="ask-micro" role="status" style={micro}>
          Askwell holds no memory. There is nothing to delete.
        </p>
      ) : null}

      {(state === "confirming" || state === "deleting") && count > 0 ? (
        <div className="flex flex-col gap-2 px-4 py-3" style={panel}>
          <p className="ask-prose" style={{ color: "var(--alarm)" }}>
            {deleteAllConfirmationCopy(count)}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              className="ask-action-primary px-3 py-1"
              onClick={confirm}
              disabled={state === "deleting"}
            >
              Delete all {count}
            </button>
            <button
              type="button"
              className="ask-navigates px-3 py-1"
              style={outlined}
              onClick={() => setState("idle")}
              disabled={state === "deleting"}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : state === "deleted" ? (
        <p className="ask-micro" role="status" style={micro}>
          Memory is empty. Askwell will ask again when it needs to know.
        </p>
      ) : state !== "confirming" ? (
        <div>
          <button
            type="button"
            className="ask-navigates px-2 py-1"
            style={{ ...outlined, color: "var(--alarm)" }}
            onClick={start}
            disabled={state === "counting"}
          >
            {state === "counting" ? "Counting…" : "Delete all memory"}
          </button>
        </div>
      ) : null}
      <ErrorLine message={error} />
    </div>
  );
}

// --- reset --------------------------------------------------------------

type ResetState = "idle" | "loading" | "confirming" | "resetting" | "done";

function ResetAskwell() {
  const [state, setState] = useState<ResetState>("idle");
  const [preview, setPreview] = useState<ResetPreview | null>(null);
  const [result, setResult] = useState<ResetResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const start = (): void => {
    setError(null);
    setState("loading");
    fetchResetPreview()
      .then((current) => {
        setPreview(current);
        setState("confirming");
      })
      .catch((thrown: unknown) => {
        setError(thrown instanceof Error ? thrown.message : "Askwell could not prepare a reset.");
        setState("idle");
      });
  };

  const confirm = (): void => {
    setState("resetting");
    performReset()
      .then((done) => {
        setResult(done);
        setState("done");
      })
      .catch((thrown: unknown) => {
        setError(thrown instanceof Error ? thrown.message : "Askwell did not reset.");
        setState("confirming");
      });
  };

  return (
    <div className="flex flex-col gap-2">
      <h3 style={heading}>Reset Askwell</h3>
      <p className="ask-micro" style={micro}>
        Removes everything Askwell holds and starts it fresh. Your original files are never
        touched.
      </p>

      {(state === "confirming" || state === "resetting") && preview !== null ? (
        <div className="flex flex-col gap-2 px-4 py-3" style={panel}>
          <p className="ask-prose" style={{ fontWeight: 600 }}>
            {preview.original_files_statement}
          </p>
          <p className="ask-prose">Reset removes:</p>
          <ul className="ask-prose list-disc pl-5">
            {resetDestroys(preview).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <p className="ask-prose">
            Anything being added right now is stopped first, then removed with the rest.
          </p>
          <p className="ask-prose">{RESET_LOG_STATEMENT}</p>
          <p className="ask-prose" style={{ color: "var(--alarm)" }}>
            {RESET_IRREVERSIBLE}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              className="ask-action-primary px-3 py-1"
              onClick={confirm}
              disabled={state === "resetting"}
            >
              {state === "resetting" ? "Resetting…" : "Reset Askwell"}
            </button>
            <button
              type="button"
              className="ask-navigates px-3 py-1"
              style={outlined}
              onClick={() => setState("idle")}
              disabled={state === "resetting"}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : state === "done" && result !== null ? (
        <div className="flex flex-col gap-2 px-4 py-3" role="status" style={panel}>
          {resetOutcome(result).map((line) => (
            <p key={line} className="ask-prose">
              {line}
            </p>
          ))}
          <p className="ask-prose">{result.original_files_statement}</p>
          <p className="ask-prose">
            {/* A full page load, not client navigation: reset destroyed the
                session secret, and only loading the page issues a new one. */}
            <button
              type="button"
              className="ask-navigates"
              onClick={() => window.location.assign("/")}
            >
              Start again
            </button>
          </p>
        </div>
      ) : (
        <div>
          <button
            type="button"
            className="ask-navigates px-2 py-1"
            style={{ ...outlined, color: "var(--alarm)" }}
            onClick={start}
            disabled={state === "loading"}
          >
            {state === "loading" ? "Checking what would be removed…" : "Reset Askwell"}
          </button>
        </div>
      )}
      <ErrorLine message={error} />
    </div>
  );
}
