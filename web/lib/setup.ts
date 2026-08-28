/**
 * The first-run sequence's API surface. `docs/ux/first-run.md`, `M1-LIB-FE-052`.
 *
 * `askwell.setup` (server) owns the machine check, the model download and the
 * two decisions this offers (skip, passphrase). This is the fetch layer only.
 */

export interface HardwareProfile {
  tier: "light" | "standard" | "accelerated" | "workstation";
  ram_gb: number;
  gpu_detected: boolean;
  vram_gb: number | null;
  floor_met: boolean;
  expectation: string;
  source: "basic-probe" | "fallback";
}

export type ModelDownloadStatus =
  | "idle"
  | "downloading"
  | "paused"
  | "verifying"
  | "ready"
  | "failed";

export interface ModelDownloadState {
  status: ModelDownloadStatus;
  tier: string;
  display_name: string;
  downloaded_bytes: number;
  total_bytes: number;
  fraction: number;
  error: string | null;
  target_path: string;
}

export interface SetupState {
  profile: HardwareProfile;
  model: ModelDownloadState;
  welcome_skipped: boolean;
  passphrase_offered: boolean;
}

export interface NoDiskSpaceError {
  error: string;
  needed_bytes: number;
  free_bytes: number;
}

export function isNoDiskSpaceError(body: unknown): body is NoDiskSpaceError {
  return (
    typeof body === "object" &&
    body !== null &&
    "needed_bytes" in body &&
    "free_bytes" in body
  );
}

async function asJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error ?? `Askwell answered ${response.status}.`);
  }
  return (await response.json()) as T;
}

export async function fetchSetupState(tier: string, signal?: AbortSignal): Promise<SetupState> {
  const response = await fetch(`/setup?tier=${encodeURIComponent(tier)}`, {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
  });
  return asJson<SetupState>(response);
}

/** Throws the raw response body on 409 so the caller can read `needed_bytes`. */
export async function startModelDownload(tier: string): Promise<ModelDownloadState> {
  const response = await fetch("/setup/model/start", {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({ tier }),
  });
  if (response.status === 409) {
    const body = (await response.json().catch(() => ({}))) as NoDiskSpaceError;
    throw body;
  }
  return asJson<ModelDownloadState>(response);
}

export async function cancelModelDownload(tier: string): Promise<ModelDownloadState> {
  const response = await fetch("/setup/model/cancel", {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({ tier }),
  });
  return asJson<ModelDownloadState>(response);
}

export async function verifyManualModel(tier: string): Promise<ModelDownloadState> {
  const response = await fetch("/setup/model/verify-manual", {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({ tier }),
  });
  return asJson<ModelDownloadState>(response);
}

export async function skipSetup(): Promise<void> {
  const response = await fetch("/setup/skip", { method: "POST", headers: { accept: "application/json" } });
  await asJson<{ welcome_skipped: boolean }>(response);
}

export async function decidePassphrase(enabled: boolean): Promise<void> {
  const response = await fetch("/setup/passphrase", {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  await asJson<{ enabled: boolean }>(response);
}

/** `1,048,576` → `1.0 GB`. Never more precise than a download estimate is. */
export function formatBytes(bytes: number): string {
  const gb = bytes / 1_000_000_000;
  if (gb >= 0.1) {
    return `${gb.toFixed(1)} GB`;
  }
  const mb = bytes / 1_000_000;
  return `${Math.max(1, Math.round(mb))} MB`;
}
