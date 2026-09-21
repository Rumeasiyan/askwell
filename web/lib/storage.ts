/**
 * The settings screen's storage section — `docs/ux/settings.md` §5,
 * `M7-SET-FE-148`.
 *
 * Three backend surfaces, each a thin read (and sometimes write) pair, the
 * same shape `lib/retrieval-threshold.ts` already established:
 *
 * - `GET /sources/storage` — per-source index size (`askwell.sources.
 *   storage_by_source`). Read-only: there is nothing here to change, only
 *   to show, and to act on elsewhere (deleting a source).
 * - `GET`/`POST /log-budget` — the log budget, current use, and now
 *   `configured_bytes` alongside the effective `budget_bytes` (issue 484),
 *   so a change silently capped by free disk can be explained rather than
 *   left to look like it did not take.
 * - `GET`/`POST /log-budget/retention` — the interaction retention window.
 *   Changing it is a decisions record on the server
 *   (`askwell.log_budget.set_retention_months`); it does not itself prune
 *   anything older than the window, because the prune that acts on this
 *   value is `M7-LOG-BE-154`, not yet built (`docs/decisions.md`, this
 *   date). The number is real and recorded; the enforcement is not there
 *   yet, and the storage section says so rather than implying otherwise.
 */

export interface SourceStorage {
  id: string;
  name: string;
  kind: string;
  status: string;
  index_bytes: number | null;
}

export async function fetchSourceStorage(signal?: AbortSignal): Promise<SourceStorage[]> {
  const response = await fetch("/sources/storage", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} about per-source storage.`);
  }
  return (await response.json()) as SourceStorage[];
}

export interface LogBudgetUsage {
  interactions_bytes: number;
  traces_bytes: number;
  used_bytes: number;
  budget_bytes: number;
  configured_bytes: number;
  free_disk_bytes: number;
  stage: "ok" | "notice" | "hard_limit";
}

/** True when the effective budget is smaller than what the user actually
 * set — the 5%-of-free-disk ceiling silently overrode their choice
 * (issue 484). `budget_bytes` alone cannot say this; it takes both
 * fields. */
export function cappedByFreeDisk(usage: Pick<LogBudgetUsage, "budget_bytes" | "configured_bytes">): boolean {
  return usage.budget_bytes < usage.configured_bytes;
}

export async function fetchLogBudget(signal?: AbortSignal): Promise<LogBudgetUsage> {
  const response = await fetch("/log-budget", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} about the log budget.`);
  }
  return (await response.json()) as LogBudgetUsage;
}

export async function setLogBudget(
  budgetBytes: number,
  signal?: AbortSignal,
): Promise<LogBudgetUsage> {
  const response = await fetch("/log-budget", {
    method: "POST",
    ...(signal ? { signal } : {}),
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ budget_bytes: budgetBytes }),
  });
  if (!response.ok) {
    throw new Error(`Askwell could not change the log budget (${response.status}).`);
  }
  return (await response.json()) as LogBudgetUsage;
}

export async function fetchRetentionMonths(signal?: AbortSignal): Promise<number> {
  const response = await fetch("/log-budget/retention", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} about the retention window.`);
  }
  const body = (await response.json()) as { months: number };
  return body.months;
}

export async function setRetentionMonths(months: number, signal?: AbortSignal): Promise<number> {
  const response = await fetch("/log-budget/retention", {
    method: "POST",
    ...(signal ? { signal } : {}),
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ months }),
  });
  if (!response.ok) {
    throw new Error(`Askwell could not change the retention window (${response.status}).`);
  }
  const body = (await response.json()) as { months: number };
  return body.months;
}
