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

export function useDocumentDate(documentId: string, enabled: boolean): DocumentDate {
  const [date, setDate] = useState<DocumentDate>(LOADING);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void fetch(`/documents/${documentId}`, { cache: "no-store" })
      .then((response) =>
        response.ok
          ? (response.json() as Promise<{
              added_at: string | null;
              superseded_by: string | null;
              superseded_at: string | null;
            }>)
          : null,
      )
      .then((body) => {
        if (cancelled || body === null) return;
        setDate({
          addedAt: body.added_at,
          supersededBy: body.superseded_by,
          supersededAt: body.superseded_at,
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [documentId, enabled]);

  return date;
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
