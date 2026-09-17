"use client";

import { useCallback, useEffect, useState } from "react";

import { correctFact, deleteFact } from "@/lib/memory-chips";
import {
  EMPTY_MEMORY_COPY,
  EMPTY_MEMORY_CTA,
  NO_FILTERS,
  addManualFact,
  applyMemoryFilters,
  confirmFact,
  deleteAllConfirmationCopy,
  deleteAllMemory,
  deletedSourceNote,
  factDateLabel,
  fetchMemoryScreen,
  inferredReviewSentence,
  memorySources,
  originLabel,
  usageSentence,
  type MemoryFilters,
  type MemoryRow,
  type MemoryScreenState,
} from "@/lib/memory";

/**
 * The memory screen: the list, confidence markers, usage count — and now
 * every interaction `docs/ux/memory.md` §4 names: Edit, Confirm, Delete,
 * History, Filter, Add a fact. `M3-MEM-FE-084`.
 *
 * The whole screen is re-fetched after any write rather than patched
 * locally: a correction can change a row's history, a confirm changes its
 * marker, and a delete can change `inferredCount` — re-reading the same
 * `GET /memory` the initial load used keeps all of that consistent with
 * the server's own view rather than re-deriving it here.
 */
export function MemoryScreen() {
  const [state, setState] = useState<MemoryScreenState | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [filters, setFilters] = useState<MemoryFilters>(NO_FILTERS);
  const [addingFact, setAddingFact] = useState(false);
  const [deletingAll, setDeletingAll] = useState(false);

  const reload = useCallback((signal?: AbortSignal) => {
    fetchMemoryScreen(signal)
      .then((screen) => {
        setState(screen);
        setFailure(null);
      })
      .catch((error: unknown) => {
        if (signal?.aborted) return;
        setFailure(String(error));
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    reload(controller.signal);
    return () => controller.abort();
  }, [reload]);

  const rows = state?.rows ?? [];
  const filteredRows = applyMemoryFilters(rows, filters);
  const sources = memorySources(rows);

  return (
    <section className="flex flex-col gap-4">
      <div>
        <h1 style={{ fontSize: "var(--t-display)", lineHeight: "var(--t-display-lh)" }}>Memory</h1>
        <p className="ask-prose mt-1" style={{ color: "var(--muted)" }}>
          What Askwell believes about your material, and where each belief came from.
        </p>
        {state !== null && state.inferredCount > 0 ? (
          <p className="ask-micro mt-1" style={{ color: "var(--inferred)" }}>
            {inferredReviewSentence(state.inferredCount)}
          </p>
        ) : null}
      </div>

      {failure !== null ? (
        <p className="ask-prose" style={{ color: "var(--alarm)" }}>
          Askwell is not answering about memory.
        </p>
      ) : state === null ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          Reading memory…
        </p>
      ) : state.rows.length === 0 ? (
        <EmptyMemory />
      ) : (
        <>
          <MemoryFilterBar
            filters={filters}
            onChange={setFilters}
            sources={sources}
            totalCount={rows.length}
            visibleCount={filteredRows.length}
          />

          <div className="flex flex-col gap-2">
            {filteredRows.map((row) => (
              <MemoryRowCard
                key={`${row.factKind}:${row.id}`}
                row={row}
                onChanged={() => reload()}
              />
            ))}
            {filteredRows.length === 0 ? (
              <p className="ask-prose" style={{ color: "var(--muted)" }}>
                Nothing matches this filter.
              </p>
            ) : null}
          </div>

          <DeleteAllMemory
            count={rows.length}
            confirming={deletingAll}
            onStart={() => setDeletingAll(true)}
            onCancel={() => setDeletingAll(false)}
            onDeleted={() => {
              setDeletingAll(false);
              reload();
            }}
          />
        </>
      )}

      <AddManualFact
        open={addingFact}
        onOpen={() => setAddingFact(true)}
        onClose={() => setAddingFact(false)}
        onAdded={() => {
          setAddingFact(false);
          reload();
        }}
      />
    </section>
  );
}

function EmptyMemory() {
  return (
    <div
      className="flex flex-col gap-2 px-4 py-3"
      style={{ background: "var(--surface)", borderRadius: "var(--radius)" }}
    >
      <p className="ask-prose">{EMPTY_MEMORY_COPY}</p>
      <a className="ask-navigates ask-micro" href="/clarifications">
        {EMPTY_MEMORY_CTA}
      </a>
    </div>
  );
}

/** `docs/ux/memory.md` §2's three filters — narrowing only, never a second
 * request, since the full list is already in hand. */
function MemoryFilterBar({
  filters,
  onChange,
  sources,
  totalCount,
  visibleCount,
}: {
  filters: MemoryFilters;
  onChange: (filters: MemoryFilters) => void;
  sources: { id: string; name: string | null }[];
  totalCount: number;
  visibleCount: number;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <label className="ask-micro flex items-center gap-1.5">
        <input
          type="checkbox"
          checked={filters.inferredOnly}
          onChange={(event) => onChange({ ...filters, inferredOnly: event.target.checked })}
        />
        Inferred only
      </label>
      <label className="ask-micro flex items-center gap-1.5">
        <input
          type="checkbox"
          checked={filters.unusedOnly}
          onChange={(event) => onChange({ ...filters, unusedOnly: event.target.checked })}
        />
        Unused
      </label>
      {sources.length > 0 ? (
        <label className="ask-micro flex items-center gap-1.5">
          Source
          <select
            className="ask-input px-2"
            value={filters.sourceId ?? ""}
            onChange={(event) =>
              onChange({ ...filters, sourceId: event.target.value === "" ? null : event.target.value })
            }
          >
            <option value="">All</option>
            {sources.map((source) => (
              <option key={source.id} value={source.id}>
                {source.name ?? source.id}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {visibleCount !== totalCount ? (
        <span className="ask-micro" style={{ color: "var(--muted)" }}>
          {visibleCount} of {totalCount}
        </span>
      ) : null}
    </div>
  );
}

function MemoryRowCard({ row, onChanged }: { row: MemoryRow; onChanged: () => void }) {
  const deletedNote = deletedSourceNote(row);
  const date = factDateLabel(row.createdAt);

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(row.value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<string | null>(null);

  const startEdit = (): void => {
    setDraft(row.value);
    setError(null);
    setEditing(true);
  };

  const save = async (): Promise<void> => {
    const value = draft.trim();
    if (value === "" || value === row.value) {
      setEditing(false);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { reprocessing } = await correctFact(row.factKind, row.id, value);
      setConfirmation(reprocessing.label);
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That correction failed.");
    } finally {
      setBusy(false);
    }
  };

  const confirm = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const { alreadyConfirmed } = await confirmFact(row.factKind, row.id);
      setConfirmation(alreadyConfirmed ? "Already confirmed." : "Confirmed.");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That confirmation failed.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const { reprocessing } = await deleteFact(row.factKind, row.id);
      setConfirmation(`Deleted. ${reprocessing.label}`);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That deletion failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="flex flex-col gap-1.5 px-4 py-3"
      style={{ background: "var(--surface)", borderRadius: "var(--radius)" }}
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className="flex items-center gap-1.5 ask-micro" style={{ fontFamily: "var(--font-mono)" }}>
          <span className="ask-confidence-marker" data-supplied={row.origin !== "inferred"} aria-hidden="true" />
          {row.subject}
        </span>
        {row.sourceName !== null ? (
          <span className="ask-micro" style={{ color: "var(--muted)" }}>
            {row.sourceName}
          </span>
        ) : null}
      </div>

      {editing ? (
        <div className="flex flex-col gap-2">
          <textarea
            className="ask-input p-2"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={2}
            autoFocus
          />
          <div className="flex gap-2">
            <button
              type="button"
              className="ask-action-primary px-3 py-1"
              onClick={() => void save()}
              disabled={busy || draft.trim() === ""}
            >
              Save
            </button>
            <button
              type="button"
              className="ask-navigates px-3 py-1"
              onClick={() => setEditing(false)}
              disabled={busy}
              style={{ border: "1px solid var(--rule-strong)" }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <p className="ask-prose">{row.value}</p>
      )}

      <p className="ask-micro" style={{ color: row.origin === "inferred" ? "var(--inferred)" : "var(--muted)" }}>
        {originLabel(row.origin)}
        {date !== null ? ` · ${date}` : ""} · {usageSentence(row.usageCount)}
      </p>
      {deletedNote !== null ? (
        <p className="ask-micro" style={{ color: "var(--muted)" }}>
          {deletedNote}
        </p>
      ) : null}
      {row.history.length > 0 ? <MemoryHistory row={row} /> : null}

      {!editing ? (
        <div className="flex gap-2 mt-1">
          {row.origin === "inferred" ? (
            <button
              type="button"
              className="ask-navigates px-3 py-1"
              onClick={() => void confirm()}
              disabled={busy}
              style={{ border: "1px solid var(--rule-strong)" }}
            >
              Confirm
            </button>
          ) : null}
          <button
            type="button"
            className="ask-navigates px-3 py-1"
            onClick={startEdit}
            disabled={busy}
            style={{ border: "1px solid var(--rule-strong)" }}
          >
            Edit
          </button>
          <button
            type="button"
            className="ask-navigates px-3 py-1"
            onClick={() => void remove()}
            disabled={busy}
            style={{ border: "1px solid var(--rule-strong)" }}
          >
            Delete
          </button>
        </div>
      ) : null}

      {error !== null ? (
        <p className="ask-micro" style={{ color: "var(--alarm)" }}>
          {error}
        </p>
      ) : confirmation !== null ? (
        <p className="ask-micro" style={{ color: "var(--muted)" }}>
          {confirmation}
        </p>
      ) : null}
    </div>
  );
}

/** `docs/ux/memory.md` §5, "Conflicting facts": the later value wins as the
 * row itself; every earlier value stays visible here, struck through,
 * rather than discarded. */
function MemoryHistory({ row }: { row: MemoryRow }) {
  return (
    <div className="flex flex-col gap-0.5 mt-1" style={{ borderLeft: "2px solid var(--rule)", paddingLeft: "8px" }}>
      {row.history.map((entry, index) => {
        const date = factDateLabel(entry.createdAt);
        return (
          <p key={index} className="ask-micro" style={{ color: "var(--muted)", textDecoration: "line-through" }}>
            {entry.value}
            {date !== null ? ` · ${date}` : ""}
          </p>
        );
      })}
    </div>
  );
}

/**
 * Manual entry — `docs/ux/memory.md` §4: "for someone who wants to tell
 * Askwell something before being asked." A subject that already has an
 * active fact is offered back as a correction rather than silently
 * doubling up (the ticket's own edge case).
 */
function AddManualFact({
  open,
  onOpen,
  onClose,
  onAdded,
}: {
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  onAdded: () => void;
}) {
  const [subject, setSubject] = useState("");
  const [fact, setFact] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<{ factId: string; subject: string; value: string } | null>(
    null,
  );

  if (!open) {
    return (
      <button type="button" className="ask-navigates ask-micro" onClick={onOpen}>
        Add a fact
      </button>
    );
  }

  const reset = (): void => {
    setSubject("");
    setFact("");
    setError(null);
    setDuplicate(null);
  };

  const submit = async (): Promise<void> => {
    const s = subject.trim();
    const f = fact.trim();
    if (s === "" || f === "") return;
    setBusy(true);
    setError(null);
    setDuplicate(null);
    try {
      const result = await addManualFact(s, f);
      if (result.duplicate && result.existing !== null) {
        setDuplicate(result.existing);
        return;
      }
      reset();
      onAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That fact could not be added.");
    } finally {
      setBusy(false);
    }
  };

  const correctExisting = async (): Promise<void> => {
    if (duplicate === null) return;
    setBusy(true);
    setError(null);
    try {
      await correctFact("memory", duplicate.factId, fact.trim());
      reset();
      onAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That correction failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="flex flex-col gap-2 px-4 py-3"
      style={{ background: "var(--surface)", borderRadius: "var(--radius)" }}
    >
      <p className="ask-micro">Tell Askwell something before it asks.</p>
      <input
        type="text"
        className="ask-input px-3"
        placeholder="Subject, e.g. RFQ"
        value={subject}
        onChange={(event) => setSubject(event.target.value)}
        disabled={busy}
      />
      <textarea
        className="ask-input p-2"
        placeholder="What it means, e.g. Request for Quotation"
        rows={2}
        value={fact}
        onChange={(event) => setFact(event.target.value)}
        disabled={busy}
      />
      {duplicate !== null ? (
        <div className="flex flex-col gap-2">
          <p className="ask-micro" style={{ color: "var(--inferred)" }}>
            Askwell already knows {duplicate.subject}: {duplicate.value}. Correct it instead?
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              className="ask-action-primary px-3 py-1"
              onClick={() => void correctExisting()}
              disabled={busy}
            >
              Correct it
            </button>
            <button
              type="button"
              className="ask-navigates px-3 py-1"
              onClick={() => setDuplicate(null)}
              disabled={busy}
              style={{ border: "1px solid var(--rule-strong)" }}
            >
              Never mind
            </button>
          </div>
        </div>
      ) : (
        <div className="flex gap-2">
          <button
            type="button"
            className="ask-action-primary px-3 py-1"
            onClick={() => void submit()}
            disabled={busy || subject.trim() === "" || fact.trim() === ""}
          >
            Add
          </button>
          <button
            type="button"
            className="ask-navigates px-3 py-1"
            onClick={() => {
              reset();
              onClose();
            }}
            disabled={busy}
            style={{ border: "1px solid var(--rule-strong)" }}
          >
            Cancel
          </button>
        </div>
      )}
      {error !== null ? (
        <p className="ask-micro" style={{ color: "var(--alarm)" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Delete-all-memory. This ticket's own Validation Rule: the confirmation
 * names the count and that it cannot be undone — `deleteAllConfirmationCopy`
 * is that copy, shown inline rather than via a native `confirm()` so it
 * reads like the rest of the screen.
 */
function DeleteAllMemory({
  count,
  confirming,
  onStart,
  onCancel,
  onDeleted,
}: {
  count: number;
  confirming: boolean;
  onStart: () => void;
  onCancel: () => void;
  onDeleted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confirmDelete = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await deleteAllMemory(count);
      onDeleted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That deletion failed.");
    } finally {
      setBusy(false);
    }
  };

  if (!confirming) {
    return (
      <button type="button" className="ask-navigates ask-micro" style={{ color: "var(--alarm)" }} onClick={onStart}>
        Delete all memory
      </button>
    );
  }

  return (
    <div
      className="flex flex-col gap-2 px-4 py-3"
      style={{ background: "var(--surface)", borderRadius: "var(--radius)" }}
    >
      <p className="ask-prose" style={{ color: "var(--alarm)" }}>
        {deleteAllConfirmationCopy(count)}
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          className="ask-action-primary px-3 py-1"
          onClick={() => void confirmDelete()}
          disabled={busy}
        >
          Delete all {count}
        </button>
        <button
          type="button"
          className="ask-navigates px-3 py-1"
          onClick={onCancel}
          disabled={busy}
          style={{ border: "1px solid var(--rule-strong)" }}
        >
          Cancel
        </button>
      </div>
      {error !== null ? (
        <p className="ask-micro" style={{ color: "var(--alarm)" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
