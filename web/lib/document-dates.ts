"use client";

import { useEffect, useState } from "react";

/**
 * A cited document's dates and current supersession status, for the
 * conflicting-sources card (`docs/ux/ask.md` §5, `M2-PARTIAL-FE-058`).
 *
 * `GET /documents/{id}` is reused for this rather than a new field on the
 * `citation` SSE event: it carries both dates and `superseded_by` /
 * `superseded_at`, which is also the edge case this ticket names — "the
 * superseded one is labelled as such". Fetched per document, on demand,
 * the same pattern `SupersededBanner` (`context-rail.tsx`) already uses
 * for the same endpoint, rather than growing the streamed citation payload
 * for data only the conflict card needs.
 *
 * **Two different dates, never interchangeable** (`M7-FIX-BE-170a`).
 * `documentDate` is the document's own — from its metadata or its filename,
 * as `documentDateSource` says — and arrives no more precise than it is
 * known: `"2026"`, `"2026-03"` or `"2026-03-15"`, with
 * `documentDatePrecision` naming which. `null` means unknown and must read
 * as "Date unknown", never as `addedAt`, which is only when Askwell
 * ingested the file.
 */
export type DocumentDatePrecision = "day" | "month" | "year";
export type DocumentDateSource = "metadata" | "filename";

export interface DocumentDate {
  addedAt: string | null;
  documentDate: string | null;
  documentDatePrecision: DocumentDatePrecision | null;
  documentDateSource: DocumentDateSource | null;
  supersededBy: string | null;
  supersededAt: string | null;
}

function fetchDocumentDate(documentId: string): Promise<DocumentDate | null> {
  return fetch(`/documents/${documentId}`, { cache: "no-store" })
    .then((response) =>
      response.ok
        ? (response.json() as Promise<{
            added_at: string | null;
            document_date?: string | null;
            document_date_precision?: DocumentDatePrecision | null;
            document_date_source?: DocumentDateSource | null;
            superseded_by: string | null;
            superseded_at: string | null;
          }>)
        : null,
    )
    .then((body) =>
      body === null
        ? null
        : {
            addedAt: body.added_at,
            documentDate: body.document_date ?? null,
            documentDatePrecision: body.document_date_precision ?? null,
            documentDateSource: body.document_date_source ?? null,
            supersededBy: body.superseded_by,
            supersededAt: body.superseded_at,
          },
    )
    .catch(() => null);
}

/**
 * Every one of `documentIds`' dates, fetched in parallel, keyed by document
 * id. Issue GH-226: a conflicting-sources list has to be *sorted* by date
 * before it renders, which needs every card's date known up front — a card
 * fetching its own date alone could not see its siblings' dates and so cannot decide where in the list it belongs.
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
 * newest-first by the document's *own* date (`M7-FIX-BE-170a`) — never by
 * `addedAt`, which would rank a 2024 file added after a 2026 one as the
 * newer — so the reader sees the current position before the older one it
 * disagrees with. A document whose date is unknown sorts exactly as one not
 * yet loaded does: after every dated one, before superseded ones. Ties keep
 * their original (citation-stream) order — `Array.sort` is stable, so this
 * never needs its own tie-break. Never reads model order: `docs/ux/ask.md`
 * §5's own Validation Rule ("date and supersession are the only orderings")
 * is exactly what this function is.
 *
 * `documentDate` is compared as the truncated ISO string it arrives as, so
 * `"2026-03"` outranks `"2025-12-31"` and `"2026"` against `"2026-03-15"`
 * orders the more specific first (the longer string is the greater),
 * deterministically, rather than padding a year out to a day it never
 * claimed.
 */
export function sortByDateAndSupersession<T extends { documentId: string }>(
  cards: readonly T[],
  dates: ReadonlyMap<string, DocumentDate>,
): T[] {
  const rank = (card: T): [number, string] => {
    const date = dates.get(card.documentId);
    if (date?.supersededBy != null) return [2, ""];
    if (date?.documentDate == null) return [1, ""];
    return [0, date.documentDate];
  };
  return [...cards].sort((a, b) => {
    const [aTier, aDate] = rank(a);
    const [bTier, bDate] = rank(b);
    if (aTier !== bTier) return aTier - bTier;
    return aDate === bDate ? 0 : aDate < bDate ? 1 : -1;
  });
}

/**
 * A document's own date as the conflict records and their cards show it
 * (`M7-FIX-FE-170`): `date` to the precision it is known — "2026",
 * "March 2026", "15 March 2026", never padded out to a day it never claimed
 * — and `source`, where it came from, because a file's properties are a
 * claim the file makes about itself and a re-save moves them
 * (`docs/decisions.md`, `M7-FIX-BE-170a`).
 *
 * An unknown date says so. It never falls back to `addedAt`: when Askwell
 * ingested a file says nothing about which version is current, and showing
 * it here would be a wrong fact presented as a right one. `null` only while
 * the date has not loaded, so nothing is shown rather than "unknown" too
 * early.
 */
export function documentDateLabel(
  date: DocumentDate | undefined,
  locale?: string,
): { date: string; source: string | null } | null {
  if (date === undefined) return null;
  const { documentDate, documentDatePrecision, documentDateSource } = date;
  if (documentDate === null || documentDatePrecision === null) return { date: "Date unknown", source: null };
  const [year, month = 1, day = 1] = documentDate.split("-").map(Number);
  const when = new Date(Date.UTC(year!, month - 1, day));
  const text =
    documentDatePrecision === "year"
      ? String(year)
      : when.toLocaleDateString(locale, {
          timeZone: "UTC",
          year: "numeric",
          month: "long",
          ...(documentDatePrecision === "day" ? { day: "numeric" } : {}),
        });
  const source =
    documentDateSource === "filename"
      ? "from the file name"
      : documentDateSource === "metadata"
        ? "from the file's properties"
        : null;
  return { date: text, source };
}

export function supersededDateLabel(date: Pick<DocumentDate, "supersededBy" | "supersededAt">): string | null {
  if (date.supersededBy === null) return null;
  const when = date.supersededAt !== null ? ` ${new Date(date.supersededAt).toLocaleDateString()}` : "";
  return `Superseded${when}`;
}
