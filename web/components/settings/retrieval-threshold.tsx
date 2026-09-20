"use client";

/**
 * The retrieval threshold control — "genuinely useful and genuinely
 * dangerous" (`docs/ux/trace.md` §4). One component, two call sites: the
 * abstention trace's near-miss offer (`trace-panel.tsx`, only when
 * `lib/retrieval-threshold.ts`'s `nearMiss()` finds one) and the settings
 * screen (`docs/ux/settings.md` §2), sharing this exact copy and this exact
 * un-slider shape so the warning cannot read differently in one place than
 * the other — `M5-TRACE-FE-122`'s own "same warning wherever reachable"
 * Acceptance Criteria.
 *
 * Deliberately not a slider: a number field plus an explicit "Change
 * threshold" button, so a change is a submitted decision, never a value
 * that drifted while dragging. Every submission goes through
 * `askwell.retrieve.set_retrieval_threshold`, which always writes a
 * decisions record with the old and new value — this component never
 * writes one itself, and never could bypass it.
 */

import { useEffect, useState } from "react";

import {
  fetchRetrievalThreshold,
  recordThresholdChanged,
  setRetrievalThreshold,
  type NearMiss,
} from "@/lib/retrieval-threshold";

export function RetrievalThresholdControl({ nearMiss }: { nearMiss?: NearMiss }) {
  const [current, setCurrent] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchRetrievalThreshold(controller.signal)
      .then((value) => {
        setCurrent(value);
        setInput(value.toFixed(2));
      })
      .catch((thrown: unknown) => {
        if (!controller.signal.aborted) {
          setError(
            thrown instanceof Error ? thrown.message : "Askwell could not read the current threshold.",
          );
        }
      });
    return () => controller.abort();
  }, []);

  const submit = (): void => {
    const value = Number(input);
    if (!Number.isFinite(value) || value < 0 || value > 1) {
      setError("Enter a number between 0 and 1.");
      return;
    }
    setSaving(true);
    setError(null);
    setConfirmation(null);
    void setRetrievalThreshold(value)
      .then((applied) => {
        recordThresholdChanged();
        setConfirmation(
          `Threshold changed from ${current !== null ? current.toFixed(2) : "its previous value"} to ` +
            `${applied.toFixed(2)}. Recorded in the decisions log.`,
        );
        setCurrent(applied);
      })
      .catch((thrown: unknown) => {
        setError(thrown instanceof Error ? thrown.message : "Askwell could not change the threshold.");
      })
      .finally(() => setSaving(false));
  };

  return (
    <div className="flex flex-col gap-2">
      {nearMiss !== undefined ? (
        <p className="ask-prose" style={{ margin: 0 }}>
          The closest passage scored {nearMiss.score.toFixed(2)}, just under the{" "}
          {nearMiss.threshold.toFixed(2)} threshold.
        </p>
      ) : null}
      <p className="ask-micro" style={{ textTransform: "none" }}>
        Lowering the threshold makes Askwell answer from weaker matches — more answers, more of
        them wrong. Raising it makes Askwell abstain more often — fewer answers, but every one it
        gives is more likely to be right. There is no automatic tuning: every change here is
        yours, and every change is recorded.
      </p>
      {current !== null ? (
        <p className="ask-micro" style={{ textTransform: "none" }}>
          Current threshold: {current.toFixed(2)}
        </p>
      ) : null}
      <div className="flex items-center gap-2">
        <input
          type="number"
          min={0}
          max={1}
          step={0.01}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          aria-label="New retrieval threshold"
          style={{ border: "1px solid var(--rule)", padding: "0.25rem 0.5rem", width: "5rem" }}
        />
        <button
          type="button"
          onClick={submit}
          disabled={saving || current === null}
          className="ask-navigates px-2 py-1"
          style={{ border: "1px solid var(--rule)" }}
        >
          {saving ? "Changing…" : "Change threshold"}
        </button>
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
