/**
 * Settings → Model and speed: the model in use, the swap, and the real
 * numbers. `M7-SET-FE-146`, `docs/ux/settings.md` §2, `askwell.model_select`.
 *
 * Every figure here is measured or absent — never a rating, never a zero
 * standing in for "not measured". Memory is the running process's resident
 * size as the host supervisor read it; throughput is llama.cpp's own timing
 * of real answers, averaged over the most recent ones (issue 617), with the
 * typical end-to-end answer time beside it because generation speed alone
 * does not explain a slow answer on CPU (issue 661).
 *
 * The copy lives here rather than in the component so `model.test.ts` can
 * hold it to the specification: the unverified statement is the backend's
 * own string (`UNVERIFIED_STATEMENT`, the one `POST /model/select` refuses
 * an unverified swap without), and the swap consequence always says the
 * assistant goes away briefly while search keeps working.
 */

export interface ModelCandidate {
  file: string;
  display_name: string;
  validated: boolean;
  size_bytes: number;
}

export interface Throughput {
  turns: number;
  tokens_per_second: number | null;
  prompt_tokens_per_second: number | null;
  median_answer_ms: number | null;
}

export interface ModelState {
  source: "shipped" | "user_supplied" | "none" | "unknown";
  display_name: string | null;
  state: string;
  reason: string | null;
  loaded_file: string | null;
  memory_bytes: number | null;
  acceleration: string | null;
  file_bytes: number | null;
  throughput: Throughput;
  models_dir: string;
  candidates: ModelCandidate[];
  unverified_statement: string;
  swap_timeout_seconds: number;
}

export interface SwapResult {
  ok: boolean;
  reason: string | null;
  model_file: string;
  size_warning: string | null;
}

export async function fetchModel(signal?: AbortSignal): Promise<ModelState> {
  const response = await fetch("/model", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Askwell could not read the model in use (${response.status}).`);
  }
  return (await response.json()) as ModelState;
}

/** Waits for the swap to finish — or fail and restore the previous model —
 * which can take minutes. `acknowledgedUnverified` is sent only when the
 * statement was on screen at the moment of confirming; the backend refuses
 * an unverified swap without it. */
export async function selectModel(
  modelFile: string,
  acknowledgedUnverified: boolean,
): Promise<SwapResult> {
  const response = await fetch("/model/select", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({
      model_file: modelFile,
      acknowledged_unverified: acknowledgedUnverified,
    }),
  });
  const body = (await response.json().catch(() => ({}))) as Partial<SwapResult> & {
    error?: string;
  };
  if (response.status === 422) {
    throw new Error(body.error ?? "Askwell could not use that file as a model.");
  }
  if (!response.ok && response.status !== 409) {
    throw new Error(`Askwell could not swap the model (${response.status}).`);
  }
  return {
    ok: body.ok === true,
    reason: body.reason ?? null,
    model_file: body.model_file ?? modelFile,
    size_warning: body.size_warning ?? null,
  };
}

export function formatBytes(bytes: number): string {
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`;
}

/** The memory footprint, or why there is none. */
export function memoryLine(model: ModelState): string {
  const file = model.file_bytes !== null ? ` The model file is ${formatBytes(model.file_bytes)}.` : "";
  if (model.memory_bytes !== null && model.acceleration === "gpu") {
    return `${formatBytes(model.memory_bytes)} of system memory in use by the model, measured now. The part of the model on the graphics card is not included.${file}`;
  }
  if (model.memory_bytes !== null) {
    return `${formatBytes(model.memory_bytes)} of memory in use by the model, measured now.${file}`;
  }
  if (model.state !== "ready") {
    return `Not measured — the assistant is not running.${file}`;
  }
  return `Not measured on this machine.${file}`;
}

/** Throughput, as sentences. Before any answer: says so, never "0". */
export function throughputLines(throughput: Throughput): string[] {
  if (throughput.turns === 0) {
    return [
      "Not measured yet — this model has not answered a question. Ask one, and the real " +
        "figures appear here.",
    ];
  }
  const lines: string[] = [];
  if (throughput.median_answer_ms !== null) {
    lines.push(
      `A typical answer takes ${Math.round(throughput.median_answer_ms / 1000)} seconds from ` +
        "asking to the last word.",
    );
  }
  if (throughput.prompt_tokens_per_second !== null) {
    lines.push(
      `Reading your passages: ${throughput.prompt_tokens_per_second.toFixed(0)} tokens per second.`,
    );
  }
  if (throughput.tokens_per_second !== null) {
    lines.push(`Writing the answer: ${throughput.tokens_per_second.toFixed(1)} tokens per second.`);
  }
  const answers = throughput.turns === 1 ? "answer" : "answers";
  lines.push(`Measured over the last ${throughput.turns} ${answers} from this model.`);
  return lines;
}

/** What each profile means in plain terms (`docs/architecture.md` §6). */
export const PROFILE_EXPECTATIONS: Record<string, string> = {
  light: "8 GB of memory, no graphics card. Slow but usable; voice will struggle.",
  standard: "16 GB of memory, no graphics card. Comfortable for text; voice usable.",
  accelerated: "16 GB or more with a graphics card. Fast, and voice works fully.",
  workstation: "32 GB or more with a large graphics card. Full capability.",
};

/** The swap's ceiling in words — `swap_timeout_seconds` from `GET /model`,
 * the backend's own wait, never a number re-typed here. */
export function swapCeiling(timeoutSeconds: number): string {
  const minutes = Math.round(timeoutSeconds / 60);
  return minutes >= 1
    ? `up to ${minutes} minute${minutes === 1 ? "" : "s"}`
    : `up to ${timeoutSeconds} seconds`;
}

/** Stated before a swap, every time. */
export function swapConsequence(currentName: string | null, timeoutSeconds: number): string {
  const current = currentName ?? "the current model";
  return (
    "While the new model loads, the assistant is unavailable — questions wait until it is " +
    `ready, which takes ${swapCeiling(timeoutSeconds)}. Document search, browsing and ` +
    `your library keep working throughout. If the new model fails to load, Askwell goes back to ` +
    `${current} and says why. The swap is recorded in the decisions log.`
  );
}

/** Shown while a swap runs: still unavailable, for how long at most, and
 * what keeps working (`docs/states-and-edge-cases.md` §6, "Model swap in
 * progress"). */
export function swapInProgress(name: string, timeoutSeconds: number): string {
  return (
    `Swapping to ${name}. The assistant is unavailable until it has loaded — ` +
    `${swapCeiling(timeoutSeconds)}; search and browsing still work.`
  );
}

/** The "no alternative model present" edge case: names the folder. */
export function noCandidates(modelsDir: string): string {
  return (
    `There is no other model file in ${modelsDir}. To try a different model, place its .gguf ` +
    "file in that folder and reopen this page. Askwell does not download models from here."
  );
}

export function sourceLabel(source: ModelState["source"]): string {
  switch (source) {
    case "shipped":
      return "Validated";
    case "user_supplied":
      return "Unverified";
    default:
      return "";
  }
}
