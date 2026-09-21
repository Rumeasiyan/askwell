/**
 * The passphrase control — `/settings/passphrase*` (`askwell.passphrase`,
 * `M7-SEC-BE-151`). `M7-SET-FE-147` surfaces it; it does not build the
 * mechanism, per this ticket's own Out of Scope.
 *
 * No-recovery is stated before every `set` call goes out, never assumed —
 * `acknowledged_no_recovery` is a real field the caller must set explicitly.
 */

export type Strength = "weak" | "fair" | "good" | "strong";

export interface PassphraseStatus {
  enabled: boolean;
  locked: boolean;
}

export interface StrengthResult {
  score: number;
  strength: Strength;
  meets_minimum: boolean;
  feedback: string[];
}

class PassphraseError extends Error {}

async function asJson<T>(response: Response, verb: string): Promise<T> {
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: string } | null;
    throw new PassphraseError(
      body?.error ?? `Askwell could not ${verb} the passphrase (${response.status}).`,
    );
  }
  return (await response.json()) as T;
}

export async function fetchPassphraseStatus(signal?: AbortSignal): Promise<PassphraseStatus> {
  const response = await fetch("/settings/passphrase", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  return asJson<PassphraseStatus>(response, "read");
}

export async function checkStrength(passphrase: string): Promise<StrengthResult> {
  const response = await fetch("/settings/passphrase/strength", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ passphrase }),
  });
  return asJson<StrengthResult>(response, "assess");
}

export async function setPassphrase(
  passphrase: string,
  acknowledgedNoRecovery: boolean,
): Promise<PassphraseStatus> {
  const response = await fetch("/settings/passphrase/set", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ passphrase, acknowledged_no_recovery: acknowledgedNoRecovery }),
  });
  const body = await asJson<{ enabled: boolean }>(response, "set");
  return { enabled: body.enabled, locked: false };
}

export async function changePassphrase(
  currentPassphrase: string,
  newPassphrase: string,
): Promise<PassphraseStatus> {
  const response = await fetch("/settings/passphrase/change", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({
      current_passphrase: currentPassphrase,
      new_passphrase: newPassphrase,
    }),
  });
  const body = await asJson<{ enabled: boolean }>(response, "change");
  return { enabled: body.enabled, locked: false };
}

export async function removePassphrase(
  currentPassphrase: string,
): Promise<{ status: PassphraseStatus; message: string }> {
  const response = await fetch("/settings/passphrase/remove", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ current_passphrase: currentPassphrase }),
  });
  const body = await asJson<{ enabled: boolean; message: string }>(response, "remove");
  return { status: { enabled: body.enabled, locked: false }, message: body.message };
}
