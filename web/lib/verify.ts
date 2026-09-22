/**
 * The log verifier — `docs/ux/settings.md` §6, `M7-LOG-FE-156`.
 *
 * `GET /log-verify` (`askwell.log_verify`) runs the hash-chain check across
 * both audit stores and answers once, synchronously — a read has nothing to
 * resume or retry, so there is no job to poll here the way export and prune
 * have.
 */

export interface StoreVerification {
  store: string;
  checked: number;
  intact: boolean;
  reason: string | null;
  detail: string;
  note: string;
  broken_record_id: string | null;
  broken_at: string | null;
}

export interface VerificationReport {
  intact: boolean;
  decisions: StoreVerification;
  interactions: StoreVerification;
}

export async function verifyLog(signal?: AbortSignal): Promise<VerificationReport> {
  const response = await fetch("/log-verify", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} while verifying the log.`);
  }
  return (await response.json()) as VerificationReport;
}
