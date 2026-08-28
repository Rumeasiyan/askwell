"use client";

import { useEffect, useState } from "react";

import {
  type IngestState,
  type SourceCoverage,
  coverageSentence,
  fetchIngest,
  reindexSource,
  retryDocument,
  subscribeIngest,
} from "@/lib/ingest";
import {
  DEFAULT_FILTERS,
  KIND_LABELS,
  STATUS_LABELS,
  addedSentence,
  attentionCauses,
  matchesFilters,
  type LibraryFilters,
} from "@/lib/library";

import { StatusMark } from "./status-mark";

/**
 * The library. `docs/ux/library.md`, `M1-LIB-FE-050`.
 *
 * One row per source — collections were deliberately removed, so "grouped by
 * source" means the source *is* the row, not a heading over a list of files.
 * The same `IngestState` the add screen already watches is the data here
 * too: nothing new is polled, this is a second reading of one stream.
 *
 * The empty and no-corpus states are deliberately plain. `M1-LIB-FE-051`
 * owns the taught, reviewed copy for "nothing added yet"; what is here is
 * factual placeholder text so the screen is never blank while that ticket's
 * own work is pending.
 */
export function LibraryScreen() {
  const [state, setState] = useState<IngestState | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [filters, setFilters] = useState<LibraryFilters>(DEFAULT_FILTERS);

  useEffect(() => {
    const controller = new AbortController();
    let live = true;

    fetchIngest(controller.signal)
      .then((first) => {
        if (live) setState(first);
      })
      .catch((error: unknown) => {
        if (live && !controller.signal.aborted) setFailure(String(error));
      });

    const stop = subscribeIngest((next) => {
      if (live) setState(next);
    });

    return () => {
      live = false;
      controller.abort();
      stop();
    };
  }, []);

  return (
    <section className="flex flex-col gap-4">
      <div>
        <h1 style={{ fontSize: "var(--t-display)", lineHeight: "var(--t-display-lh)" }}>
          Library
        </h1>
        <p className="ask-micro mt-1">Every source you have added, and what state it is in.</p>
      </div>

      {failure !== null ? (
        <p className="ask-prose" style={{ color: "var(--alarm)" }}>
          Askwell is not answering about the library.
        </p>
      ) : state === null ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          Reading the library…
        </p>
      ) : state.sources.length === 0 ? (
        <EmptyLibrary />
      ) : (
        <LibraryList state={state} filters={filters} onFilters={setFilters} />
      )}
    </section>
  );
}

function EmptyLibrary() {
  return (
    <div
      className="flex flex-col gap-3 px-4 py-3"
      style={{
        background: "var(--surface)",
        borderRadius: "var(--radius)",
        border: "1px solid var(--rule)",
      }}
    >
      <p className="ask-prose">
        Nothing has been added yet. Drop files or a folder anywhere on this window, or add them
        from the add-source screen.
      </p>
    </div>
  );
}

function LibraryList({
  state,
  filters,
  onFilters,
}: {
  state: IngestState;
  filters: LibraryFilters;
  onFilters: (filters: LibraryFilters) => void;
}) {
  const kinds = [...new Set(state.sources.map((source) => source.kind))];
  const statuses = [...new Set(state.sources.map((source) => source.status))];
  const rows = state.sources.filter((source) => matchesFilters(source, filters));

  return (
    <>
      <div className="flex flex-wrap items-center gap-3" role="group" aria-label="Filter the library">
        <label className="flex items-center gap-1 ask-micro">
          Kind
          <select
            value={filters.kind}
            onChange={(event) => onFilters({ ...filters, kind: event.target.value })}
            style={{
              border: "1px solid var(--rule)",
              background: "var(--sunk)",
              fontSize: "var(--t-meta)",
            }}
          >
            <option value="all">All</option>
            {kinds.map((kind) => (
              <option key={kind} value={kind}>
                {KIND_LABELS[kind] ?? kind}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1 ask-micro">
          Status
          <select
            value={filters.status}
            onChange={(event) => onFilters({ ...filters, status: event.target.value })}
            style={{
              border: "1px solid var(--rule)",
              background: "var(--sunk)",
              fontSize: "var(--t-meta)",
            }}
          >
            <option value="all">All</option>
            {statuses.map((status) => (
              <option key={status} value={status}>
                {STATUS_LABELS[status] ?? status}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1 ask-micro">
          <input
            type="checkbox"
            checked={filters.onlyOpenClarifications}
            onChange={(event) =>
              onFilters({ ...filters, onlyOpenClarifications: event.target.checked })
            }
          />
          Has open clarifications
        </label>
      </div>

      {rows.length === 0 ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          No sources match these filters.
        </p>
      ) : (
        <ul className="flex flex-col gap-2 list-none p-0">
          {rows.map((source) => (
            <SourceRow
              key={source.id}
              source={source}
              state={state}
            />
          ))}
        </ul>
      )}
    </>
  );
}

function SourceRow({ source, state }: { source: SourceCoverage; state: IngestState }) {
  const [expanded, setExpanded] = useState(false);
  const active = state.active.find((item) => item.source_id === source.id);
  const causes =
    source.status === "attention" ? attentionCauses(source.id, state.failures, state.flagged) : [];

  return (
    <li>
      <article
        className="flex flex-col gap-1 px-4 py-3"
        style={{
          background: "var(--surface)",
          border: "1px solid var(--rule)",
          borderRadius: "var(--radius)",
        }}
      >
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <span style={{ fontFamily: "var(--font-app)", fontSize: "var(--t-ui)" }}>
            {source.name ?? "Untitled source"}
          </span>
          <span className="flex items-center gap-2 ask-micro" style={{ color: "var(--muted)" }}>
            <span className="flex items-center gap-1">
              <StatusMark status={source.status} />
              {STATUS_LABELS[source.status] ?? source.status}
            </span>
          </span>
        </div>

        <p className="ask-micro" style={{ color: "var(--muted)" }}>
          {KIND_LABELS[source.kind] ?? source.kind} · Added {addedSentence(source.added_at)}
          {source.open_clarifications > 0
            ? ` · ${source.open_clarifications} open clarification${source.open_clarifications === 1 ? "" : "s"}`
            : ""}
        </p>

        <p className="ask-micro">
          {coverageSentence(source)}
          {active === undefined
            ? ""
            : ` Indexing ${active.filename}${active.fraction === null ? "" : ` (${Math.round(active.fraction * 100)}%)`} now.`}
        </p>

        {causes.length === 0 ? null : (
          <>
            <button
              type="button"
              onClick={() => setExpanded((was) => !was)}
              className="ask-navigates self-start px-2 py-1"
              style={{ border: "1px solid var(--rule)", fontSize: "var(--t-meta)" }}
              aria-expanded={expanded}
            >
              {expanded ? "Hide detail" : `Show detail (${causes.length})`}
            </button>
            {expanded ? <AttentionDetail sourceId={source.id} causes={causes} /> : null}
          </>
        )}

        <ReindexControl sourceId={source.id} name={source.name ?? "this source"} />
      </article>
    </li>
  );
}

function AttentionDetail({
  sourceId,
  causes,
}: {
  sourceId: string;
  causes: ReturnType<typeof attentionCauses>;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  return (
    <ul className="mt-1 flex flex-col gap-1 list-none p-0" aria-label={`Why ${sourceId} needs attention`}>
      {causes.map((cause) => (
        <li key={cause.documentId} className="ask-micro">
          <span style={{ color: cause.fixable ? "var(--alarm)" : "var(--inferred)" }}>
            {cause.filename}: {cause.sentence}
          </span>
          {cause.fixable ? (
            <>
              {" "}
              <button
                type="button"
                disabled={busy === cause.documentId}
                onClick={() => {
                  setBusy(cause.documentId);
                  retryDocument(cause.documentId)
                    .then(() => {
                      setErrors((was) => {
                        const { [cause.documentId]: _removed, ...rest } = was;
                        return rest;
                      });
                    })
                    .catch((error: unknown) => {
                      setErrors((was) => ({ ...was, [cause.documentId]: String(error) }));
                    })
                    .finally(() => setBusy(null));
                }}
                className="ask-navigates px-2 py-1"
                style={{ border: "1px solid var(--rule)", fontSize: "var(--t-meta)" }}
              >
                {busy === cause.documentId ? "Trying again…" : "Try again"}
              </button>
            </>
          ) : null}
          {errors[cause.documentId] === undefined ? null : (
            <span className="ask-micro mt-1 block" style={{ color: "var(--alarm)" }}>
              {errors[cause.documentId]}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

/**
 * Re-index, with the confirmation `docs/ux/library.md` §3 requires before it
 * starts. Inline rather than a modal — the same pattern `Folders`
 * (`web/components/settings/folders.tsx`) already uses for a consequential
 * action, so a user who has seen one has seen the other.
 */
function ReindexControl({ sourceId, name }: { sourceId: string; name: string }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (result !== null) {
    return (
      <p className="ask-micro mt-1" style={{ color: "var(--muted)" }}>
        {result}
      </p>
    );
  }

  if (!confirming) {
    return (
      <div className="mt-1">
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="ask-navigates px-2 py-1"
          style={{ border: "1px solid var(--rule)", color: "var(--muted)", fontSize: "var(--t-meta)" }}
        >
          Re-index
        </button>
      </div>
    );
  }

  return (
    <div className="mt-1 flex flex-col gap-2">
      <p className="ask-micro">
        Re-index {name}? Askwell reads every file in it again from scratch — extracting,
        chunking and embedding. On a large source this can take hours, and answers about it may
        be thin until it finishes.
      </p>
      {error === null ? null : (
        <p className="ask-micro" style={{ color: "var(--alarm)" }}>
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setError(null);
            reindexSource(sourceId)
              .then((count) => {
                setConfirming(false);
                setResult(
                  count === 0
                    ? "Nothing in this source to re-index."
                    : `Re-indexing ${count} document${count === 1 ? "" : "s"}.`,
                );
              })
              .catch((reason: unknown) => setError(String(reason)))
              .finally(() => setBusy(false));
          }}
          className="ask-navigates px-3 py-1"
          style={{ border: "1px solid var(--rule-strong)", fontSize: "var(--t-ui)" }}
        >
          {busy ? "Starting…" : "Re-index it"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => setConfirming(false)}
          className="ask-navigates px-3 py-1"
          style={{ border: "1px solid var(--rule)", fontSize: "var(--t-ui)" }}
        >
          Not now
        </button>
      </div>
    </div>
  );
}

