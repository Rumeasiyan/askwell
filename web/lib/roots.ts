/**
 * The folders Askwell has been given permission to read.
 *
 * Askwell indexes in place and copies nothing, so it has to be told which
 * folders it may open. This is the client half of that registry.
 *
 * The one thing this module must never do is collapse the four ways a folder
 * can be unreadable into "unavailable". They have four different fixes, and a
 * user whose USB drive is unplugged and a user whose `.env` needs a line are
 * looking for different things entirely.
 */

export type MountState = "available" | "unavailable" | "unreadable" | "not_mounted";

export interface Root {
  id: string;
  path: string;
  name: string;
  state: MountState;
  reason: string | null;
  warning: string | null;
  filesystem: string | null;
  network_share: boolean;
  added_at: string;
}

export interface RemovedRoot {
  id: string;
  path: string;
  name: string;
}

export interface Registry {
  /** The local counter, and the only analytics here. It goes nowhere (C1). */
  count: number;
  roots: Root[];
  removed: RemovedRoot[];
  /** The one part of the filesystem the containers can see, or null. */
  mount: string | null;
}

export interface Removal {
  path: string;
  sources_affected: number;
  /** Written by the API, shown verbatim. It is the only warning before this. */
  consequence: string;
}

/** What each state is called where the user can see it. */
export const STATE_LABELS: Record<MountState, string> = {
  available: "Readable",
  unavailable: "Not connected",
  unreadable: "Not permitted",
  not_mounted: "Needs a restart",
};

/**
 * The colour a state is rendered in.
 *
 * `available` is deliberately **not** `--provenance`. That colour is reserved
 * for claims traceable to a source and appears on nothing else
 * (`docs/ux/design-system.md` §2); spending it on a settings row would make it
 * mean "fine" everywhere, and it would stop meaning "traceable".
 *
 * `not_mounted` is `--inferred` rather than `--alarm`: nothing is broken and
 * nothing is lost, there is a configuration line to add. `--alarm` is failures
 * only.
 */
export function stateColour(state: MountState): string {
  if (state === "available") return "var(--muted)";
  if (state === "unreadable") return "var(--alarm)";
  return "var(--inferred)";
}

export async function readRegistry(): Promise<Registry> {
  const response = await fetch("/roots", { cache: "no-store" });
  if (!response.ok) throw new Error(`Askwell answered with ${response.status}.`);
  return (await response.json()) as Registry;
}

/**
 * Nominate a folder.
 *
 * The path is a string and that is the seam. `M7-TAURI-FE-182` replaces the
 * typed field with the platform's own directory dialog, which hands back
 * exactly this — so the picker arrives without touching the registry, the
 * validation, or what removing a folder does. A browser upload control would
 * have had to be undone: it copies bytes, and Askwell copies nothing.
 */
export async function nominate(path: string): Promise<void> {
  const response = await fetch("/roots", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!response.ok) {
    const body = (await response.json()) as { error?: string };
    throw new Error(body.error ?? `Askwell answered with ${response.status}.`);
  }
}

export async function previewRemoval(id: string): Promise<Removal> {
  const response = await fetch(`/roots/${id}/removal`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Askwell answered with ${response.status}.`);
  return (await response.json()) as Removal;
}

export async function unnominate(id: string): Promise<Removal> {
  const response = await fetch(`/roots/${id}`, { method: "DELETE" });
  if (!response.ok) throw new Error(`Askwell answered with ${response.status}.`);
  return (await response.json()) as Removal;
}
