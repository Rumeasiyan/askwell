/**
 * The proxy's own counters — `GET /network` (`askwell.network.read_activity`).
 * `M7-SET-FE-147`, `docs/ux/settings.md` §4.
 *
 * The number is the proof of C1: it has to come from the egress proxy, never
 * be invented by the application, and it must never read as zero when it is
 * actually unreadable. This file only ever passes the server's own shape
 * through — no client-side fallback to zero exists anywhere here.
 */

export interface Refusal {
  service: string;
  destination: string;
}

export interface NetworkActivity {
  available: boolean;
  refused: number | null;
  permitted: number | null;
  recent: Refusal[];
  recent_capped_at: number;
  unavailable_reason: string | null;
}

export async function fetchNetworkActivity(signal?: AbortSignal): Promise<NetworkActivity> {
  const response = await fetch("/network", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} about network activity.`);
  }
  return (await response.json()) as NetworkActivity;
}
