"use client";

/**
 * The current hardware profile, with the override this ticket adds.
 * `M7-PROBE-FE-138`, `docs/ux/settings.md` §2.
 *
 * Below the floor or after a probe failure, the welcome screen already
 * warns and continues (`welcome-screen.tsx`'s `StepMachineCheck`) — this is
 * the other half: the profile can be changed **afterwards**, from here, and
 * the consequence is stated every time, the same "permit it, state the
 * consequence, never make it frictionless" pattern
 * `retrieval-threshold.tsx` already uses. Never a confirm dialog — the
 * consequence text sits next to the button precisely so it cannot be
 * dismissed unread.
 */

import { useEffect, useState } from "react";

import {
  PROFILES,
  fetchProbe,
  overrideConsequence,
  overrideProfile,
  rerunProbe,
  type Profile,
  type ProbeState,
} from "@/lib/probe";

const PROFILE_LABELS: Record<Profile, string> = {
  light: "Light",
  standard: "Standard",
  accelerated: "Accelerated",
  workstation: "Workstation",
};

export function HardwareProfile() {
  const [state, setState] = useState<ProbeState | null>(null);
  const [selected, setSelected] = useState<Profile>("standard");
  const [busy, setBusy] = useState<"rerun" | "override" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchProbe(controller.signal)
      .then((probe) => {
        setState(probe);
        setSelected(probe.profile);
      })
      .catch((thrown: unknown) => {
        if (!controller.signal.aborted) {
          setError(
            thrown instanceof Error ? thrown.message : "Askwell could not read the hardware probe.",
          );
        }
      });
    return () => controller.abort();
  }, []);

  function rerun(): void {
    setBusy("rerun");
    setError(null);
    setConfirmation(null);
    void rerunProbe()
      .then((probe) => {
        setState(probe);
        setSelected(probe.profile);
      })
      .catch((thrown: unknown) => {
        setError(thrown instanceof Error ? thrown.message : "The re-run did not complete.");
      })
      .finally(() => setBusy(null));
  }

  function applyOverride(): void {
    setBusy("override");
    setError(null);
    setConfirmation(null);
    void overrideProfile(selected)
      .then((probe) => {
        setState(probe);
        setConfirmation(`Profile changed to ${PROFILE_LABELS[probe.profile]}. Recorded in the decisions log.`);
      })
      .catch((thrown: unknown) => {
        setError(thrown instanceof Error ? thrown.message : "Askwell could not change the profile.");
      })
      .finally(() => setBusy(null));
  }

  if (error !== null && state === null) {
    return (
      <p className="ask-micro" style={{ color: "var(--alarm)" }}>
        {error}
      </p>
    );
  }

  if (state === null) {
    return <p className="ask-micro">Reading the hardware probe…</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="ask-prose" style={{ margin: 0 }}>
        Current profile: <strong>{PROFILE_LABELS[state.profile]}</strong>
        {state.overridden ? ` (measured as ${PROFILE_LABELS[state.detected_profile]})` : ""}
      </p>
      <p className="ask-micro" style={{ textTransform: "none" }}>
        {state.reason}
      </p>
      {state.detection_failed ? (
        <p className="ask-micro" style={{ textTransform: "none", color: "var(--inferred)" }}>
          The probe could not measure this machine, so Askwell is running on the standard
          profile as a fallback.
        </p>
      ) : state.below_floor ? (
        <p className="ask-micro" style={{ textTransform: "none", color: "var(--inferred)" }}>
          Below what Askwell is built for. It runs, but slowly, and voice will likely not work.
        </p>
      ) : null}

      <div>
        <button
          type="button"
          disabled={busy !== null}
          onClick={rerun}
          className="ask-navigates px-2 py-1"
          style={{ border: "1px solid var(--rule)" }}
        >
          {busy === "rerun" ? "Re-running…" : "Re-run the probe"}
        </button>
      </div>

      <div className="flex flex-col gap-2 mt-1" style={{ borderTop: "1px solid var(--rule)", paddingTop: "0.75rem" }}>
        <p className="ask-micro" style={{ textTransform: "none" }}>
          Override the profile. {overrideConsequence(selected)}
        </p>
        <div className="flex items-center gap-2">
          <select
            value={selected}
            onChange={(event) => setSelected(event.target.value as Profile)}
            aria-label="Profile to switch to"
            style={{ border: "1px solid var(--rule)", padding: "0.25rem 0.5rem" }}
          >
            {PROFILES.map((tier) => (
              <option key={tier} value={tier}>
                {PROFILE_LABELS[tier]}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={busy !== null || selected === state.profile}
            onClick={applyOverride}
            className="ask-navigates px-2 py-1"
            style={{ border: "1px solid var(--rule)" }}
          >
            {busy === "override" ? "Changing…" : "Change profile"}
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
