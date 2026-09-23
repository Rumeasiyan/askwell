/**
 * The model in use, and the swap — `GET`/`POST /model`
 * (`askwell.model_select.register_model_select`, `M7-SET-BE-145a`).
 *
 * `M7-SET-FE-146`'s own edge case: no throughput field exists here because
 * nothing in the backend yet measures tokens per second from a real turn
 * (`docs/decisions.md`, this ticket's date — filed as a follow-up issue
 * rather than invented). Memory footprint is real: the active model file's
 * size on disk, not the resident RAM `llama-server` actually holds, which
 * this process has no way to read.
 */

export type ModelSource = "shipped" | "user_supplied" | "none" | "unknown";

export interface ModelAlternative {
  tier: string;
  display_name: string;
  filename: string;
  path: string;
}

export interface ModelState {
  source: ModelSource;
  display_name: string | null;
  user_model_path: string | null;
  expected_path: string;
  alternatives: ModelAlternative[];
  active_model_size_gb: number | null;
}

export interface ModelSwapResult {
  ok: boolean;
  reason: string | null;
  model_path: string;
  size_warning: string | null;
}

export async function fetchModelState(signal?: AbortSignal): Promise<ModelState> {
  const response = await fetch("/model", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} about the model in use.`);
  }
  return (await response.json()) as ModelState;
}

/** Swapping is permitted regardless of validation status — the consequence
 * is stated by the caller before this runs, never enforced here
 * (`docs/ux/settings.md` §2, this ticket's own Validation Rule). A `422`
 * means the path was rejected before any swap was attempted; a non-ok
 * `ok: false` body means the swap itself failed and the previous model was
 * restored, named in `reason`. */
export async function selectModel(modelPath: string): Promise<ModelSwapResult> {
  const response = await fetch("/model/select", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ model_path: modelPath }),
  });
  const body = (await response.json()) as ModelSwapResult | { error: string };
  if (response.status === 422 && "error" in body) {
    throw new Error(body.error);
  }
  return body as ModelSwapResult;
}

// A local counter of model swaps (this ticket's own Analytics Events line)
// — in-memory only, never persisted or transmitted (C1), same shape as
// `lib/retrieval-threshold.ts`'s own counter.
let modelSwapCount = 0;

export function recordModelSwapped(): void {
  modelSwapCount += 1;
}

export function getModelSwapCount(): number {
  return modelSwapCount;
}
