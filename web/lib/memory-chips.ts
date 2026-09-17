import type { AskFactCitationData } from "@/lib/ask";

/**
 * One memory chip, rendered next to the claim that cited it. `M3-CORRECT-FE-081`.
 *
 * Unlike a citation (`lib/citations.ts`), never grouped: a chip is rendered
 * once per `fact_citation` event, right after the claim it belongs to,
 * because `docs/ux/ask.md` §4 wants a visible chip in the prose itself —
 * `st_cd = student status code` — not a hidden marker resolved through the
 * margin. The same fact cited by two different claims in one answer
 * produces two chips, one per claim, which is correct: each is a separate
 * place in the text a reader might want to correct it from.
 */
export interface FactChip {
  claimOrdinal: number;
  factKind: "memory" | "schema_note";
  factId: string;
  subject: string;
  fact: string;
  origin: string;
  confidence: number | null;
  suppliedAt: string | null;
}

/**
 * Fold one `fact_citation` event into the chip list. Pure, mirroring
 * `applyCitation`'s own reasoning: a reconnect replaying this turn's history
 * must not draw a second chip for the same (claim, fact) pair.
 */
export function applyFactCitation(
  chips: readonly FactChip[],
  data: AskFactCitationData,
): FactChip[] {
  const exists = chips.some(
    (chip) =>
      chip.claimOrdinal === data.claim_ordinal &&
      chip.factKind === data.fact_kind &&
      chip.factId === data.fact_id,
  );
  if (exists) return chips.slice();
  return [
    ...chips,
    {
      claimOrdinal: data.claim_ordinal,
      factKind: data.fact_kind,
      factId: data.fact_id,
      subject: data.subject,
      fact: data.fact,
      origin: data.origin,
      confidence: data.confidence,
      suppliedAt: data.supplied_at,
    },
  ];
}

/** What a chip's popover shows once opened — a fresh read, since the chip's
 * own data is a snapshot from when the answer was composed and the ticket's
 * own edge case is that the fact may have moved on since
 * (`GET /memory/facts/{kind}/{id}`, `askwell.memory.get_fact_detail`). */
export interface FactDetail {
  factKind: "memory" | "schema_note";
  id: string;
  subject: string;
  value: string;
  origin: string;
  createdAt: string | null;
  usageCount: number;
  active: boolean;
  current: FactDetail | null;
}

interface FactDetailWire {
  fact_kind: "memory" | "schema_note";
  id: string;
  subject: string;
  value: string;
  origin: string;
  created_at: string | null;
  usage_count: number;
  active: boolean;
  current: FactDetailWire | null;
}

function fromWire(wire: FactDetailWire): FactDetail {
  return {
    factKind: wire.fact_kind,
    id: wire.id,
    subject: wire.subject,
    value: wire.value,
    origin: wire.origin,
    createdAt: wire.created_at,
    usageCount: wire.usage_count,
    active: wire.active,
    current: wire.current !== null ? fromWire(wire.current) : null,
  };
}

/** What a correction or deletion just queued — the confirmation naming what
 * is being re-read, `docs/ux/ask.md` §4's own acceptance criterion. */
export interface FactReprocessing {
  count: number;
  label: string;
  changed: boolean;
}

interface CorrectFactResponse {
  fact_id: string;
  reprocessing: FactReprocessing;
  reapply_job_id: string | null;
}

interface DeleteFactResponse {
  reprocessing: FactReprocessing;
  reapply_job_id: string | null;
}

export class FactNotFoundError extends Error {}

async function parseOrThrow<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) {
    if (response.status === 404) throw new FactNotFoundError(fallback);
    const body = (await response.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error ?? fallback);
  }
  return (await response.json()) as T;
}

export async function fetchFactDetail(
  factKind: "memory" | "schema_note",
  factId: string,
): Promise<FactDetail> {
  const response = await fetch(`/memory/facts/${factKind}/${factId}`, {
    headers: { accept: "application/json" },
  });
  const wire = await parseOrThrow<FactDetailWire>(response, "That fact could not be read.");
  return fromWire(wire);
}

/** Correct a fact from its chip. `askwell.memory.correct_fact` decides
 * in-place supersession vs. a fresh user-origin write depending on whether
 * the fact is currently user-supplied or inferred — this call is the same
 * either way. */
export async function correctFact(
  factKind: "memory" | "schema_note",
  factId: string,
  value: string,
): Promise<{ factId: string; reprocessing: FactReprocessing }> {
  const response = await fetch(`/memory/facts/${factKind}/${factId}/correct`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ value }),
  });
  const body = await parseOrThrow<CorrectFactResponse>(response, "That correction failed.");
  return { factId: body.fact_id, reprocessing: body.reprocessing };
}

export async function deleteFact(
  factKind: "memory" | "schema_note",
  factId: string,
): Promise<{ reprocessing: FactReprocessing }> {
  const response = await fetch(`/memory/facts/${factKind}/${factId}/delete`, {
    method: "POST",
  });
  const body = await parseOrThrow<DeleteFactResponse>(response, "That deletion failed.");
  return { reprocessing: body.reprocessing };
}

// A local counter of corrections made from a chip (this ticket's own
// Analytics Events line) — in-memory only, never persisted or transmitted
// (C1), same shape as `citations.ts`'s `cardClickCount`.
let chipCorrectionCount = 0;

export function recordChipCorrection(): void {
  chipCorrectionCount += 1;
}

export function getChipCorrectionCount(): number {
  return chipCorrectionCount;
}
