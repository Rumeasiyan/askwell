"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  correctFact,
  deleteFact,
  fetchFactDetail,
  recordChipCorrection,
  type FactChip,
  type FactDetail,
} from "@/lib/memory-chips";

/**
 * A memory fact used in an answer, rendered as a visible chip right after
 * the claim it supports (`docs/ux/ask.md` §4: "it appears as a chip:
 * `st_cd = student status code`") — deliberately not a hidden marker like a
 * document citation, since a chip that cannot be seen cannot be clicked.
 * `M3-CORRECT-FE-081`.
 *
 * Its own file, split out of `ask-screen.tsx`, because `trace-panel.tsx`
 * needs the identical component for its own memory-fact rows
 * (`M5-TRACE-FE-121`: "clicking a memory fact opens the same popover as in
 * an answer") — importing it back from `ask-screen.tsx` there would be a
 * circular import (`ask-screen.tsx` already imports `TraceToggle` from
 * `trace-panel.tsx`).
 */
export function MemoryChip({ chip }: { chip: FactChip }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (event: MouseEvent): void => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <span ref={wrapRef} style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        className="ask-memory-chip"
        data-open={open}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span
          className="ask-confidence-marker"
          data-supplied={chip.origin !== "inferred"}
          aria-hidden="true"
        />
        {chip.subject} = {chip.fact}
      </button>
      {open ? <MemoryFactPopover chip={chip} onClose={() => setOpen(false)} /> : null}
    </span>
  );
}

function originLabel(origin: string): string {
  return origin === "inferred" ? "I guessed" : "You told me";
}

function factDateLabel(iso: string | null): string | null {
  if (iso === null) return null;
  return new Date(iso).toLocaleDateString(undefined, { month: "long", day: "numeric" });
}

/**
 * The chip's popover: the fact, its origin and date, **Correct** and
 * **Delete** — `docs/ux/ask.md` §4. Fetches a fresh `FactDetail` on open
 * rather than trusting the chip's own snapshot, since the ticket's own edge
 * case is that the version an answer used may already be superseded — the
 * same reason a fact deleted since the trace's own turn (`M5-TRACE-FE-121`'s
 * own edge case) surfaces as `error`, below, rather than a stale popover.
 *
 * Correcting or deleting always targets the *current* active row
 * (`detail.current?.id ?? detail.id`) — never the chip's own `factId`,
 * which may already be superseded and would just 404 (`askwell.memory.
 * correct_fact`/`delete_fact` only ever act on an active row).
 */
function MemoryFactPopover({ chip, onClose }: { chip: FactChip; onClose: () => void }) {
  const [detail, setDetail] = useState<FactDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState<string | null>(null);

  const load = useCallback(() => {
    fetchFactDetail(chip.factKind, chip.factId)
      .then(setDetail)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "That fact could not be read.");
      });
  }, [chip.factKind, chip.factId]);

  useEffect(() => {
    load();
  }, [load]);

  const current = detail?.current ?? detail;

  const startEdit = (): void => {
    setDraft(current?.value ?? chip.fact);
    setConfirmation(null);
    setEditing(true);
  };

  const save = async (): Promise<void> => {
    const value = draft.trim();
    if (value === "" || current === null || current === undefined) return;
    setBusy(true);
    setError(null);
    try {
      const { reprocessing } = await correctFact(chip.factKind, current.id, value);
      recordChipCorrection();
      setConfirmation(reprocessing.label);
      setEditing(false);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That correction failed.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (): Promise<void> => {
    if (current === null || current === undefined) return;
    setBusy(true);
    setError(null);
    try {
      const { reprocessing } = await deleteFact(chip.factKind, current.id);
      setConfirmation(`Deleted. ${reprocessing.label}`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That deletion failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ask-memory-popover" role="dialog" aria-label="Memory fact">
      <div className="flex items-start justify-between gap-2">
        <span className="ask-micro">
          {chip.factKind === "schema_note" ? "Schema note" : "Memory fact"}
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="ask-micro"
          style={{ background: "none", border: "none", cursor: "pointer" }}
        >
          ×
        </button>
      </div>
      {error !== null ? (
        <p className="ask-micro" style={{ color: "var(--alarm)", textTransform: "none" }}>
          {error}
        </p>
      ) : null}
      {detail === null && error === null ? <p className="ask-micro">Loading…</p> : null}
      {detail !== null ? (
        <div className="flex flex-col gap-2">
          <p style={{ fontFamily: "var(--font-app)", fontSize: "var(--t-ui)", margin: 0 }}>
            <strong>{current?.subject ?? detail.subject}</strong> — {current?.value ?? detail.value}
          </p>
          <p className="ask-micro" style={{ textTransform: "none" }}>
            {originLabel(detail.origin)}
            {factDateLabel(detail.createdAt) !== null ? ` · ${factDateLabel(detail.createdAt)}` : ""}
            {" · used in "}
            {detail.usageCount} answer{detail.usageCount === 1 ? "" : "s"}
          </p>
          {!detail.active ? (
            <p className="ask-micro" style={{ color: "var(--inferred)", textTransform: "none" }}>
              This answer used an earlier version. Shown above is the current one.
            </p>
          ) : null}
          {editing ? (
            <div className="flex flex-col gap-2">
              <textarea
                className="ask-input p-2"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                rows={3}
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
            <div className="flex gap-2">
              <button
                type="button"
                className="ask-navigates px-3 py-1"
                onClick={startEdit}
                disabled={busy}
                style={{ border: "1px solid var(--rule-strong)" }}
              >
                Correct
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
          )}
          {confirmation !== null ? (
            <p className="ask-micro" style={{ textTransform: "none" }}>
              {confirmation}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
