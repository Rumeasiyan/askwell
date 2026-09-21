/**
 * The settings screen's "Verify the log" action — `docs/ux/settings.md`
 * §6/§8, ticket `M7-LOG-FE-156`. Thin reads over `askwell.log_verify`'s
 * three routes, the same shape `lib/storage.ts` already established for a
 * background job with progress.
 */

export interface StoreOutcome {
  total: number;
  checked: number;
  intact: boolean | null;
  break_id: string | null;
  break_at: string | null;
  break_reason: "altered" | "unlinked" | "forked" | "missing_genesis" | null;
  break_detail: string | null;
}

export interface VerifyJob {
  id: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  decisions: StoreOutcome;
  interactions: StoreOutcome;
  error: string | null;
}

export function isFinished(job: Pick<VerifyJob, "status">): boolean {
  return job.status !== "queued" && job.status !== "running";
}

export async function createVerify(signal?: AbortSignal): Promise<VerifyJob> {
  const response = await fetch("/log-verify", {
    method: "POST",
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Askwell could not start verification (${response.status}).`);
  }
  return (await response.json()) as VerifyJob;
}

export async function fetchVerify(jobId: string, signal?: AbortSignal): Promise<VerifyJob> {
  const response = await fetch(`/log-verify/${jobId}`, {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} about the verification.`);
  }
  return (await response.json()) as VerifyJob;
}

export async function cancelVerify(jobId: string, signal?: AbortSignal): Promise<VerifyJob> {
  const response = await fetch(`/log-verify/${jobId}/cancel`, {
    method: "POST",
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Askwell could not cancel the verification (${response.status}).`);
  }
  return (await response.json()) as VerifyJob;
}
