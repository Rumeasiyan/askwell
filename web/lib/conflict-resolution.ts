/**
 * "Which one is current?" — the conflict resolve offer (`docs/ux/ask.md` §5:
 * "Offers to resolve, which writes a memory fact"). `M9-FIX-FE-204`, GH-728.
 *
 * The browser names only the turn and the document. The server builds the
 * fact from the answer's own conflict line and the documents the turn cited
 * (`askwell.conflict_resolution`), so nothing typed here reaches memory.
 */

import type { CitationCard } from "./citations.ts";
import { sortByDateAndSupersession, type DocumentDate } from "./document-dates.ts";

/** One button per cited document, in the order the conflict records above
 * it use. The turn's citations are one per chunk, so a document cited for
 * two positions would otherwise offer itself twice. */
export function conflictChoices(
  citations: readonly CitationCard[],
  dates: ReadonlyMap<string, DocumentDate>,
): CitationCard[] {
  const seen = new Set<string>();
  const documents = citations.filter((card) => {
    if (seen.has(card.documentId)) return false;
    seen.add(card.documentId);
    return true;
  });
  return sortByDateAndSupersession(documents, dates);
}

export interface ConflictResolution {
  factId: string;
  subject: string;
  fact: string;
  /** `false` when this was already the remembered choice. */
  written: boolean;
}

interface ConflictResolutionWire {
  fact_id: string;
  subject: string;
  fact: string;
  written: boolean;
}

export async function resolveConflict(messageId: string, documentId: string): Promise<ConflictResolution> {
  const response = await fetch(`/ask/${encodeURIComponent(messageId)}/resolve-conflict`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ document_id: documentId }),
  });
  if (!response.ok) {
    // The server names why (not a conflict, not a cited document); say that
    // rather than a bare status.
    const payload = (await response.json().catch(() => null)) as { error?: string } | null;
    throw new Error(payload?.error ?? `Askwell answered ${response.status} saving that choice.`);
  }
  const wire = (await response.json()) as ConflictResolutionWire;
  return { factId: wire.fact_id, subject: wire.subject, fact: wire.fact, written: wire.written };
}
