"use client";

/**
 * Model in use, memory footprint and swap — `M7-SET-FE-146`,
 * `docs/ux/settings.md` §2.
 *
 * **No throughput figure here.** The ticket's own Assumption is "throughput
 * can be measured from real turns rather than a synthetic benchmark" — true
 * in principle, but nothing in the backend yet records a turn's token count
 * or duration anywhere `GET /model` (or any endpoint) can read it back from
 * (`api/src/askwell/inference/client.py`'s `StreamChunk` carries no token
 * count, and `messages` has no rolling-average column). Inventing a number
 * here would be exactly the failure this repository's own `AGENTS.md` §4
 * warns against — filed as a follow-up rather than guessed at
 * (`docs/decisions.md`, this ticket's date). Memory footprint is real: the
 * active model file's size on disk.
 *
 * Swapping is never blocked, and the unverified-model statement is shown at
 * every swap this control performs — `POST /model/select` always marks the
 * result `user_supplied` (`askwell.model_select.select_user_model`), so
 * there is no swap path here that could validly skip it.
 */

import { useEffect, useState } from "react";

import {
  fetchModelState,
  recordModelSwapped,
  selectModel,
  type ModelState,
} from "@/lib/model";

const SOURCE_LABEL: Record<ModelState["source"], string> = {
  shipped: "Validated",
  user_supplied: "Unverified",
  none: "No model loaded",
  unknown: "Unknown",
};

const UNVERIFIED_STATEMENT =
  "This model has not been tested against Askwell's checks. Citations and “I don’t " +
  "know” are behaviours Askwell verifies for the models it ships. With your own model, " +
  "they are not guaranteed.";

const UNAVAILABILITY_STATEMENT =
  "Swapping makes the assistant briefly unavailable while the new model loads. Browsing and " +
  "retrieval keep working during that time.";

function formatSize(gb: number | null): string {
  if (gb === null) return "unavailable";
  return `${gb.toFixed(1)} GB`;
}

export function ModelSwap() {
  const [state, setState] = useState<ModelState | null>(null);
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchModelState(controller.signal)
      .then(setState)
      .catch((thrown: unknown) => {
        if (!controller.signal.aborted) {
          setError(thrown instanceof Error ? thrown.message : "Askwell could not read the model in use.");
        }
      });
    return () => controller.abort();
  }, []);

  function refresh(): void {
    void fetchModelState().then(setState);
  }

  function swap(targetPath: string): void {
    if (targetPath.trim() === "") {
      setError("Give the full path to a model file.");
      return;
    }
    setBusy(true);
    setError(null);
    setConfirmation(null);
    void selectModel(targetPath)
      .then((outcome) => {
        recordModelSwapped();
        if (outcome.ok) {
          setConfirmation(
            `Swapped to ${targetPath}. ${outcome.size_warning ?? ""} Recorded in the decisions log.`.trim(),
          );
          setPath("");
        } else {
          setError(
            `The swap failed: ${outcome.reason ?? "unknown reason"}. The previous model is still in use.`,
          );
        }
        refresh();
      })
      .catch((thrown: unknown) => {
        setError(thrown instanceof Error ? thrown.message : "Askwell could not swap the model.");
      })
      .finally(() => setBusy(false));
  }

  if (error !== null && state === null) {
    return (
      <p className="ask-micro" style={{ color: "var(--alarm)" }}>
        {error}
      </p>
    );
  }

  if (state === null) {
    return <p className="ask-micro">Reading the model in use…</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="ask-prose" style={{ margin: 0 }}>
        Model in use: <strong>{state.display_name ?? "None"}</strong>{" "}
        <span
          className="ask-micro"
          style={{
            color: state.source === "user_supplied" ? "var(--inferred)" : "var(--muted)",
          }}
        >
          ({SOURCE_LABEL[state.source]})
        </span>
      </p>
      {state.source === "user_supplied" ? (
        <p className="ask-micro" style={{ textTransform: "none", color: "var(--inferred)" }}>
          {UNVERIFIED_STATEMENT}
        </p>
      ) : null}
      <p className="ask-micro" style={{ textTransform: "none" }}>
        Memory footprint: {formatSize(state.active_model_size_gb)}
      </p>
      <p className="ask-micro" style={{ textTransform: "none" }}>
        Throughput: not yet measured. Askwell does not yet track tokens per second from real
        turns.
      </p>

      <div
        className="flex flex-col gap-2 mt-1"
        style={{ borderTop: "1px solid var(--rule)", paddingTop: "0.75rem" }}
      >
        <p className="ask-micro" style={{ textTransform: "none" }}>
          {UNAVAILABILITY_STATEMENT} {UNVERIFIED_STATEMENT}
        </p>

        {state.alternatives.length > 0 ? (
          <div className="flex flex-col gap-1">
            <p className="ask-micro" style={{ textTransform: "none" }}>
              Found in the models directory:
            </p>
            {state.alternatives.map((alt) => (
              <div key={alt.path} className="flex items-center gap-2">
                <span className="ask-micro" style={{ textTransform: "none" }}>
                  {alt.display_name} ({alt.filename})
                </span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => swap(alt.path)}
                  className="ask-navigates px-2 py-1"
                  style={{ border: "1px solid var(--rule)" }}
                >
                  Swap to this model
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="ask-micro" style={{ textTransform: "none" }}>
            No alternative model found. Place a GGUF file at {state.expected_path} or elsewhere
            in the same directory to swap to it.
          </p>
        )}

        <p className="ask-micro" style={{ textTransform: "none" }}>
          Or give a full path to a model file:
        </p>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={path}
            onChange={(event) => setPath(event.target.value)}
            placeholder="/path/to/model.gguf"
            aria-label="Path to a model file to swap to"
            style={{ border: "1px solid var(--rule)", padding: "0.25rem 0.5rem", flex: 1 }}
          />
          <button
            type="button"
            disabled={busy}
            onClick={() => swap(path)}
            className="ask-navigates px-2 py-1"
            style={{ border: "1px solid var(--rule)" }}
          >
            {busy ? "Swapping…" : "Swap"}
          </button>
        </div>
      </div>

      {confirmation !== null ? (
        <p className="ask-micro" style={{ textTransform: "none" }}>
          {confirmation}
        </p>
      ) : null}
      {error !== null ? (
        <p className="ask-micro" style={{ textTransform: "none", color: "var(--alarm)" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
