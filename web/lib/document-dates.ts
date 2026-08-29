"use client";

import { useEffect, useState } from "react";

/**
 * A cited document's date and current supersession status, for the
 * conflicting-sources card (`docs/ux/ask.md` §5, `M2-PARTIAL-FE-058`).
 *
 * `GET /documents/{id}` is reused for this rather than a new field on the
 * `citation` SSE event: it already carries `added_at` (the ticket's own
 * fallback — "where neither [ingestion metadata nor a filename date]
 * exists, the added date is used and labelled as such", and neither of
 * those two is extracted anywhere in this codebase yet) and `superseded_by`
 * / `superseded_at`, which is also the edge case this ticket names — "the
 * superseded one is labelled as such". Fetched per document, on demand,
 * the same pattern `SupersededBanner` (`context-rail.tsx`) already uses
 * for the same endpoint, rather than growing the streamed citation payload
 * for data only the conflict card needs.
 */
export interface DocumentDate {
  addedAt: string | null;
  supersededBy: string | null;
  supersededAt: string | null;
}

const LOADING: DocumentDate = { addedAt: null, supersededBy: null, supersededAt: null };

function fetchDocumentDate(documentId: string): Promise<DocumentDate | null> {
  return fetch(`/documents/${documentId}`, { cache: "no-store" })
    .then((response) =>
      response.ok
        ? (response.json() as Promise<{
            added_at: string | null;
            superseded_by: string | null;
            superseded_at: string | null;
          }>)
        : null,
    )
    .then((body) =>
      body === null
        ? null
        : { addedAt: body.added_at, supersededBy: body.superseded_by, supersededAt: body.superseded_at },
    )
    .catch(() => null);
}

export function useDocumentDate(documentId: string, enabled: boolean): DocumentDate {
  const [date, setDate] = useState<DocumentDate>(LOADING);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void fetchDocumentDate(documentId).then((result) => {
      if (!cancelled && result !== null) setDate(result);
    });
    return () => {
      cancelled = true;
    };
  }, [documentId, enabled]);

  return date;
}

/**
 * Every one of `documentIds`' dates, fetched in parallel, keyed by document
 * id. Issue GH-226: a conflicting-sources list has to be *sorted* by date
 * before it renders, which needs every card's date known up front — a card
 * calling `useDocumentDate` for itself alone (above) cannot see its
 * siblings' dates and so cannot decide where in the list it belongs.
 */
export function useDocumentDates(documentIds: readonly string[], enabled: boolean): ReadonlyMap<string, DocumentDate> {
  const [dates, setDates] = useState<ReadonlyMap<string, DocumentDate>>(new Map());
  const key = enabled ? documentIds.join(",") : "";

  useEffect(() => {
    if (!enabled || documentIds.length === 0) return;
    let cancelled = false;
    void Promise.all(documentIds.map((id) => fetchDocumentDate(id).then((date) => [id, date] as const))).then(
      (entries) => {
        if (cancelled) return;
        const next = new Map<string, DocumentDate>();
        for (const [id, date] of entries) {
          if (date !== null) next.set(id, date);
        }
        setDates(next);
      },
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` is `documentIds` collapsed to a stable string
  }, [key, enabled]);

  return dates;
}

/**
 * Conflicting-sources card order: superseded sources demoted to the end
 * (never shown as an equal, per this ticket's own edge case), the rest
 * newest-first by `addedAt` so the reader sees the current position before
 * the older one it disagrees with. A document whose date has not loaded yet
 * sorts after every dated one but before superseded ones, and ties among
 * undated documents keep their original (citation-stream) order — `Array.sort`
 * is stable, so this never needs its own tie-break. Never reads model order:
 * `docs/ux/ask.md` §5's own Validation Rule ("date and supersession are the
 * only orderings") is exactly what this function is.
 */
export function sortByDateAndSupersession<T extends { documentId: string }>(
  cards: readonly T[],
  dates: ReadonlyMap<string, DocumentDate>,
): T[] {
  const rank = (card: T): [number, number] => {
    const date = dates.get(card.documentId);
    if (date?.supersededBy != null) return [2, 0];
    if (date?.addedAt == null) return [1, 0];
    return [0, -Date.parse(date.addedAt)];
  };
  return [...cards].sort((a, b) => {
    const [aTier, aTime] = rank(a);
    const [bTier, bTime] = rank(b);
    return aTier !== bTier ? aTier - bTier : aTime - bTime;
  });
}

/** "Added 3 June 2026" — labelled, per the ticket's own fallback rule,
 * since no other date source exists yet. `null` while the fetch is
 * outstanding or the endpoint gave nothing back. */
export function addedDateLabel(date: Pick<DocumentDate, "addedAt">): string | null {
  if (date.addedAt === null) return null;
  return `Added ${new Date(date.addedAt).toLocaleDateString()}`;
}

export function supersededDateLabel(date: Pick<DocumentDate, "supersededBy" | "supersededAt">): string | null {
  if (date.supersededBy === null) return null;
  const when = date.supersededAt !== null ? ` ${new Date(date.supersededAt).toLocaleDateString()}` : "";
  return `Superseded${when}`;
}
