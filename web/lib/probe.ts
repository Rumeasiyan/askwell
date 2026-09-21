/**
 * The hardware probe's current state and the settings override.
 * `M7-PROBE-FE-138`, `askwell.probe` (`M7-PROBE-DEPLOY-137`).
 *
 * `GET /probe` is the real host probe's last result when `askwell-probe`
 * has ever run on this machine, or the interim in-container reading
 * reshaped into the same field names when it has not — either way, one
 * shape, so this file and the settings screen need only one code path.
 */

export const PROFILES = ["light", "standard", "accelerated", "workstation"] as const;
export type Profile = (typeof PROFILES)[number];

export interface ProbeState {
  profile: Profile;
  reason: string;
  detection_failed: boolean;
  below_floor: boolean;
  ram_gb: number | null;
  ram_source: string;
  disk_free_gb: number;
  platform: string;
  probed_at: number;
  stale: boolean;
  overridden: boolean;
  detected_profile: Profile;
}

interface ProbeResponse {
  probe: ProbeState;
  recorded: boolean;
}

async function asProbe(response: Response, verb: string): Promise<ProbeState> {
  if (!response.ok) {
    throw new Error(`Askwell could not ${verb} the hardware probe (${response.status}).`);
  }
  const body = (await response.json()) as ProbeResponse;
  return body.probe;
}

export async function fetchProbe(signal?: AbortSignal): Promise<ProbeState> {
  const response = await fetch("/probe", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  return asProbe(response, "read");
}

/** Asks the host script, watching for this request, to measure again. */
export async function rerunProbe(): Promise<ProbeState> {
  const response = await fetch("/probe/rerun", {
    method: "POST",
    headers: { accept: "application/json" },
  });
  return asProbe(response, "re-run");
}

/** Never refused on hardware grounds — the machine can always be told to run
 * as a profile it did not measure into. The consequence (the assistant may
 * fail to load, and reports that failure if it does) is stated by the
 * caller, not enforced here. */
export async function overrideProfile(tier: Profile): Promise<ProbeState> {
  const response = await fetch("/probe/override", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ tier }),
  });
  return asProbe(response, "change");
}

/** The consequence stated before an override is submitted — this ticket's
 * own "permitted, with the consequence stated" requirement, same pattern as
 * `lib/retrieval-threshold.ts`'s warning: shown every time, not just once. */
export function overrideConsequence(tier: Profile): string {
  return (
    `Askwell will run as ${tier} without checking whether this machine can actually support ` +
    `it. If it cannot load a model at that level, the assistant will report the failure ` +
    `clearly — document search and indexing keep working either way. Recorded in the ` +
    `decisions log.`
  );
}
