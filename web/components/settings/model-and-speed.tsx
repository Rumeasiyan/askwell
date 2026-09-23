"use client";

/**
 * Settings → Model and speed. `M7-SET-FE-146`, `docs/ux/settings.md` §2.
 *
 * The first settings section: the hardware profile with what it means and a
 * re-probe (`hardware-profile.tsx`, `M7-PROBE-FE-138`), the model in use with
 * its measured memory and throughput and a swap, and the retrieval threshold
 * with the trace panel's own warning (`retrieval-threshold.tsx`, shared, so
 * the copy cannot drift between the two).
 *
 * The swap follows the threshold's pattern — permitted, consequence stated,
 * never frictionless. Choosing a model opens a confirmation that states the
 * brief unavailability first, and for an unverified model, the statement
 * that citations and abstention are not guaranteed. There is no "don't show
 * again": the statement is part of every unverified swap, and the backend
 * refuses one whose request does not say it was shown.
 */

import { useCallback, useEffect, useState } from "react";

import { HardwareProfile } from "@/components/settings/hardware-profile";
import { RetrievalThresholdControl } from "@/components/settings/retrieval-threshold";
import {
  fetchModel,
  memoryLine,
  noCandidates,
  selectModel,
  sourceLabel,
  swapConsequence,
  swapInProgress,
  throughputLines,
  formatBytes,
  type ModelCandidate,
  type ModelState,
} from "@/lib/model";

const heading = { fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" } as const;
const subheading = { margin: 0, fontWeight: 600 } as const;
const micro = { textTransform: "none" } as const;

export function ModelAndSpeed() {
  return (
    <section className="flex flex-col gap-4">
      <h2 style={heading}>Model and speed</h2>

      <div className="flex flex-col gap-2">
        <h3 className="ask-prose" style={subheading}>
          Hardware profile
        </h3>
        <HardwareProfile />
      </div>

      <div className="flex flex-col gap-2">
        <h3 className="ask-prose" style={subheading}>
          Model
        </h3>
        <ModelInUse />
      </div>

      <div className="flex flex-col gap-2">
        <h3 className="ask-prose" style={subheading}>
          Retrieval threshold
        </h3>
        <RetrievalThresholdControl />
      </div>
    </section>
  );
}

type Outcome = { kind: "ok" | "failed"; text: string; warning: string | null };

function ModelInUse() {
  const [model, setModel] = useState<ModelState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<ModelCandidate | null>(null);
  const [swapping, setSwapping] = useState<ModelCandidate | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    return fetchModel(signal)
      .then((state) => {
        setModel(state);
        setError(null);
      })
      .catch((thrown: unknown) => {
        if (!signal?.aborted) {
          setError(thrown instanceof Error ? thrown.message : "Askwell could not read the model.");
        }
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  function confirmSwap(candidate: ModelCandidate): void {
    setPending(null);
    setSwapping(candidate);
    setOutcome(null);
    // Sent only from here, with the statement on screen for this candidate.
    void selectModel(candidate.file, !candidate.validated)
      .then((result) => {
        setOutcome(
          result.ok
            ? {
                kind: "ok",
                text: `Now answering with ${candidate.display_name}. Recorded in the decisions log.`,
                warning: result.size_warning,
              }
            : {
                kind: "failed",
                // The reason is the supervisor's own account of the restore —
                // "Staying on …", or that the previous model failed to reload
                // too — and the refreshed "In use" line shows what is loaded.
                // Asserting the previous model here would be false in both of
                // those failure paths and on a timeout.
                text:
                  `The swap to ${candidate.display_name} failed: ` +
                  `${result.reason ?? "no reason was given."}`,
                warning: result.size_warning,
              },
        );
      })
      .catch((thrown: unknown) => {
        setOutcome({
          kind: "failed",
          text: thrown instanceof Error ? thrown.message : "The swap did not complete.",
          warning: null,
        });
      })
      .finally(() => {
        setSwapping(null);
        void load();
      });
  }

  if (model === null) {
    return (
      <p className="ask-micro" style={error ? { ...micro, color: "var(--alarm)" } : micro}>
        {error ?? "Reading the model in use…"}
      </p>
    );
  }

  const label = sourceLabel(model.source);

  return (
    <div className="flex flex-col gap-3">
      {model.state === "model_missing" ? (
        <div
          className="ask-prose px-4 py-3"
          style={{ border: "1px solid var(--alarm)", borderRadius: "var(--radius)" }}
        >
          <p style={{ margin: 0 }}>The model file is missing, so the assistant cannot answer.</p>
          {model.reason ? (
            <p className="ask-micro" style={micro}>
              {model.reason}
            </p>
          ) : null}
          <p className="ask-micro" style={micro}>
            Place the model file in {model.models_dir}, then restart Askwell. The manual install
            steps are the same as on the welcome screen. Document search keeps working meanwhile.
          </p>
        </div>
      ) : model.display_name === null ? (
        <p className="ask-prose" style={{ margin: 0 }}>
          No model is answering right now{model.reason ? ` — ${model.reason}` : "."} Document search
          and browsing keep working.
        </p>
      ) : (
        <p className="ask-prose" style={{ margin: 0 }}>
          In use: <strong>{model.display_name}</strong>
          {label ? (
            <span
              className="ask-micro ml-2 px-1"
              style={{
                border: `1px solid ${model.source === "user_supplied" ? "var(--inferred)" : "var(--rule)"}`,
                color: model.source === "user_supplied" ? "var(--inferred)" : undefined,
              }}
            >
              {label}
            </span>
          ) : null}
        </p>
      )}
      {model.source === "shipped" ? (
        <p className="ask-micro" style={micro}>
          Validated: this model shipped with Askwell and passed its quality checks, including
          citations and saying when it does not know.
        </p>
      ) : model.source === "user_supplied" ? (
        <p className="ask-micro" style={{ ...micro, color: "var(--inferred)" }}>
          Unverified: you supplied this model. {model.unverified_statement} Its answers are marked.
        </p>
      ) : null}

      <div className="flex flex-col gap-1">
        <p className="ask-micro" style={micro}>
          <strong>Memory.</strong> {memoryLine(model)}
        </p>
        <p className="ask-micro" style={micro}>
          <strong>Speed.</strong> {throughputLines(model.throughput).join(" ")}
        </p>
      </div>

      <div
        className="flex flex-col gap-2"
        style={{ borderTop: "1px solid var(--rule)", paddingTop: "0.75rem" }}
      >
        <p className="ask-micro" style={micro}>
          <strong>Swap model.</strong> Models are read from {model.models_dir}.
        </p>

        {swapping !== null ? (
          <p className="ask-prose" role="status" style={{ margin: 0 }}>
            {swapInProgress(swapping.display_name, model.swap_timeout_seconds)}
          </p>
        ) : model.candidates.length === 0 ? (
          <p className="ask-micro" style={micro}>
            {noCandidates(model.models_dir)}
          </p>
        ) : (
          <ul className="flex flex-col gap-2" style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {model.candidates.map((candidate) => (
              <li key={candidate.file} className="flex flex-col gap-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="ask-prose">{candidate.display_name}</span>
                  <span
                    className="ask-micro px-1"
                    style={{
                      border: `1px solid ${candidate.validated ? "var(--rule)" : "var(--inferred)"}`,
                      color: candidate.validated ? undefined : "var(--inferred)",
                    }}
                  >
                    {candidate.validated ? "Validated" : "Unverified"}
                  </span>
                  <span className="ask-micro" style={micro}>
                    {candidate.file} · {formatBytes(candidate.size_bytes)}
                  </span>
                  <button
                    type="button"
                    disabled={pending !== null}
                    onClick={() => {
                      setOutcome(null);
                      setPending(candidate);
                    }}
                    className="ask-navigates px-2 py-1"
                    style={{ border: "1px solid var(--rule)" }}
                  >
                    Swap to this model…
                  </button>
                </div>

                {pending?.file === candidate.file ? (
                  <div
                    className="flex flex-col gap-2 px-4 py-3"
                    style={{ border: "1px solid var(--rule)", borderRadius: "var(--radius)" }}
                  >
                    <p className="ask-micro" style={micro}>
                      {swapConsequence(model.display_name, model.swap_timeout_seconds)}
                    </p>
                    {candidate.validated ? null : (
                      <p
                        className="ask-prose"
                        style={{ margin: 0, color: "var(--inferred)" }}
                      >
                        {model.unverified_statement}
                      </p>
                    )}
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => confirmSwap(candidate)}
                        className="ask-navigates px-2 py-1"
                        style={{ border: "1px solid var(--rule)" }}
                      >
                        {candidate.validated ? "Swap now" : "Swap to this unverified model"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setPending(null)}
                        className="ask-navigates px-2 py-1"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}

        {outcome !== null ? (
          <p
            className="ask-micro"
            role="status"
            style={outcome.kind === "failed" ? { ...micro, color: "var(--alarm)" } : micro}
          >
            {outcome.text}
          </p>
        ) : null}
        {outcome?.warning ? (
          <p className="ask-micro" style={{ ...micro, color: "var(--inferred)" }}>
            {outcome.warning}
          </p>
        ) : null}
      </div>
    </div>
  );
}
