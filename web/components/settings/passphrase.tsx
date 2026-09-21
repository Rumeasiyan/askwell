"use client";

/**
 * The passphrase control. `M7-SET-FE-147`, `docs/ux/settings.md` §4.
 *
 * Surfaces `askwell.passphrase` (`M7-SEC-BE-151`) — off by default, and the
 * no-recovery warning sits next to the button that sets it rather than in a
 * dialog, the same "stated where it cannot be dismissed unread" pattern
 * `hardware-profile.tsx`'s override consequence already uses. Strength
 * feedback comes from the server's own heuristic (`checkStrength`), never
 * reimplemented client-side — a passphrase never leaves this input for
 * anything but that one assessment call and the eventual submit.
 */

import { useEffect, useState } from "react";

import {
  changePassphrase,
  checkStrength,
  fetchPassphraseStatus,
  removePassphrase,
  setPassphrase,
  type PassphraseStatus,
  type StrengthResult,
} from "@/lib/passphrase";

function useStrength(passphrase: string): StrengthResult | null {
  const [strength, setStrength] = useState<StrengthResult | null>(null);

  useEffect(() => {
    if (passphrase.length === 0) return;
    const timer = setTimeout(() => {
      void checkStrength(passphrase)
        .then(setStrength)
        .catch(() => setStrength(null));
    }, 250);
    return () => clearTimeout(timer);
  }, [passphrase]);

  return passphrase.length === 0 ? null : strength;
}

const STRENGTH_LABEL: Record<StrengthResult["strength"], string> = {
  weak: "Weak",
  fair: "Fair",
  good: "Good",
  strong: "Strong",
};

function StrengthMeter({ strength }: { strength: StrengthResult | null }) {
  if (strength === null) return null;
  return (
    <div className="flex flex-col gap-1">
      <p className="ask-micro" style={{ textTransform: "none" }}>
        Strength: {STRENGTH_LABEL[strength.strength]}
      </p>
      {strength.feedback.map((line) => (
        <p key={line} className="ask-micro" style={{ textTransform: "none", color: "var(--muted)" }}>
          {line}
        </p>
      ))}
    </div>
  );
}

export function PassphraseControl() {
  const [status, setStatus] = useState<PassphraseStatus | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchPassphraseStatus(controller.signal)
      .then(setStatus)
      .catch((thrown: unknown) => {
        if (!controller.signal.aborted) {
          setFailure(thrown instanceof Error ? thrown.message : "Askwell could not read the passphrase status.");
        }
      });
    return () => controller.abort();
  }, []);

  return (
    <div className="flex flex-col gap-3">
      <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>Passphrase</h3>
      {failure !== null ? (
        <p className="ask-micro" style={{ color: "var(--alarm)" }}>
          {failure}
        </p>
      ) : status === null ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          Reading…
        </p>
      ) : status.locked ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          A passphrase is set for this install but this session has not unlocked it yet.
        </p>
      ) : status.enabled ? (
        <EnabledControls onChanged={setStatus} />
      ) : (
        <DisabledControls onChanged={setStatus} />
      )}
    </div>
  );
}

function DisabledControls({ onChanged }: { onChanged: (status: PassphraseStatus) => void }) {
  const [open, setOpen] = useState(false);
  const [passphrase, setPassphraseValue] = useState("");
  const [confirm, setConfirm] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const strength = useStrength(passphrase);

  if (!open) {
    return (
      <div className="flex flex-col gap-2">
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          Off. A stolen laptop is readable as-is. Setting a passphrase encrypts your library and
          stored credentials.
        </p>
        <div>
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="ask-navigates px-2 py-1"
            style={{ border: "1px solid var(--rule)" }}
          >
            Set a passphrase
          </button>
        </div>
      </div>
    );
  }

  const canSubmit =
    strength !== null && strength.meets_minimum && passphrase === confirm && acknowledged;

  const submit = (): void => {
    setSaving(true);
    setError(null);
    void setPassphrase(passphrase, acknowledged)
      .then((next) => {
        onChanged(next);
        setOpen(false);
        setPassphraseValue("");
        setConfirm("");
        setAcknowledged(false);
      })
      .catch((thrown: unknown) => {
        setError(thrown instanceof Error ? thrown.message : "Askwell could not set the passphrase.");
      })
      .finally(() => setSaving(false));
  };

  return (
    <div className="flex flex-col gap-2">
      <p
        className="ask-prose px-4 py-3"
        style={{ background: "var(--surface)", border: "1px solid var(--rule)", borderRadius: "var(--radius)" }}
      >
        There is no recovery. Losing this passphrase means losing the library — Askwell cannot
        decrypt it for you, on this machine or any other.
      </p>
      <input
        type="password"
        value={passphrase}
        onChange={(event) => setPassphraseValue(event.target.value)}
        placeholder="New passphrase"
        aria-label="New passphrase"
        style={{ border: "1px solid var(--rule)", padding: "0.25rem 0.5rem" }}
      />
      <input
        type="password"
        value={confirm}
        onChange={(event) => setConfirm(event.target.value)}
        placeholder="Confirm passphrase"
        aria-label="Confirm new passphrase"
        style={{ border: "1px solid var(--rule)", padding: "0.25rem 0.5rem" }}
      />
      <StrengthMeter strength={strength} />
      {passphrase.length > 0 && confirm.length > 0 && passphrase !== confirm ? (
        <p className="ask-micro" style={{ color: "var(--alarm)" }}>
          Does not match.
        </p>
      ) : null}
      <label className="ask-micro flex items-center gap-2" style={{ textTransform: "none" }}>
        <input
          type="checkbox"
          checked={acknowledged}
          onChange={(event) => setAcknowledged(event.target.checked)}
        />
        I understand there is no recovery.
      </label>
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={!canSubmit || saving}
          onClick={submit}
          className="ask-navigates px-2 py-1"
          style={{ border: "1px solid var(--rule)" }}
        >
          {saving ? "Setting…" : "Set passphrase"}
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => setOpen(false)}
          className="px-2 py-1"
          style={{ border: "1px solid var(--rule)", color: "var(--muted)" }}
        >
          Cancel
        </button>
      </div>
      {error !== null ? (
        <p className="ask-micro" style={{ color: "var(--alarm)" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

function EnabledControls({ onChanged }: { onChanged: (status: PassphraseStatus) => void }) {
  const [mode, setMode] = useState<"idle" | "change" | "remove">("idle");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const strength = useStrength(next);

  const reset = (): void => {
    setMode("idle");
    setCurrent("");
    setNext("");
    setConfirm("");
    setError(null);
  };

  const submitChange = (): void => {
    setSaving(true);
    setError(null);
    void changePassphrase(current, next)
      .then((status) => {
        onChanged(status);
        setConfirmation("Passphrase changed.");
        reset();
      })
      .catch((thrown: unknown) => {
        setError(thrown instanceof Error ? thrown.message : "Askwell could not change the passphrase.");
      })
      .finally(() => setSaving(false));
  };

  const submitRemove = (): void => {
    setSaving(true);
    setError(null);
    void removePassphrase(current)
      .then(({ status, message }) => {
        onChanged(status);
        setConfirmation(message);
        reset();
      })
      .catch((thrown: unknown) => {
        setError(thrown instanceof Error ? thrown.message : "Askwell could not remove the passphrase.");
      })
      .finally(() => setSaving(false));
  };

  if (mode === "idle") {
    return (
      <div className="flex flex-col gap-2">
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          On. The library and stored credentials are encrypted with it.
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setMode("change")}
            className="ask-navigates px-2 py-1"
            style={{ border: "1px solid var(--rule)" }}
          >
            Change passphrase
          </button>
          <button
            type="button"
            onClick={() => setMode("remove")}
            className="ask-navigates px-2 py-1"
            style={{ border: "1px solid var(--rule)" }}
          >
            Remove passphrase
          </button>
        </div>
        {confirmation !== null ? (
          <p className="ask-micro" style={{ textTransform: "none" }}>
            {confirmation}
          </p>
        ) : null}
      </div>
    );
  }

  if (mode === "remove") {
    return (
      <div className="flex flex-col gap-2">
        <p
          className="ask-prose px-4 py-3"
          style={{ background: "var(--surface)", border: "1px solid var(--rule)", borderRadius: "var(--radius)" }}
        >
          Removing it decrypts the library with this machine&apos;s own key again — a stolen
          laptop becomes a data breach again.
        </p>
        <input
          type="password"
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
          placeholder="Current passphrase"
          aria-label="Current passphrase"
          style={{ border: "1px solid var(--rule)", padding: "0.25rem 0.5rem" }}
        />
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={current.length === 0 || saving}
            onClick={submitRemove}
            className="ask-navigates px-2 py-1"
            style={{ border: "1px solid var(--rule)" }}
          >
            {saving ? "Removing…" : "Remove passphrase"}
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={reset}
            className="px-2 py-1"
            style={{ border: "1px solid var(--rule)", color: "var(--muted)" }}
          >
            Cancel
          </button>
        </div>
        {error !== null ? (
          <p className="ask-micro" style={{ color: "var(--alarm)" }}>
            {error}
          </p>
        ) : null}
      </div>
    );
  }

  const canSubmit = strength !== null && strength.meets_minimum && next === confirm && current.length > 0;

  return (
    <div className="flex flex-col gap-2">
      <input
        type="password"
        value={current}
        onChange={(event) => setCurrent(event.target.value)}
        placeholder="Current passphrase"
        aria-label="Current passphrase"
        style={{ border: "1px solid var(--rule)", padding: "0.25rem 0.5rem" }}
      />
      <input
        type="password"
        value={next}
        onChange={(event) => setNext(event.target.value)}
        placeholder="New passphrase"
        aria-label="New passphrase"
        style={{ border: "1px solid var(--rule)", padding: "0.25rem 0.5rem" }}
      />
      <input
        type="password"
        value={confirm}
        onChange={(event) => setConfirm(event.target.value)}
        placeholder="Confirm new passphrase"
        aria-label="Confirm new passphrase"
        style={{ border: "1px solid var(--rule)", padding: "0.25rem 0.5rem" }}
      />
      <StrengthMeter strength={strength} />
      {next.length > 0 && confirm.length > 0 && next !== confirm ? (
        <p className="ask-micro" style={{ color: "var(--alarm)" }}>
          Does not match.
        </p>
      ) : null}
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={!canSubmit || saving}
          onClick={submitChange}
          className="ask-navigates px-2 py-1"
          style={{ border: "1px solid var(--rule)" }}
        >
          {saving ? "Changing…" : "Change passphrase"}
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={reset}
          className="px-2 py-1"
          style={{ border: "1px solid var(--rule)", color: "var(--muted)" }}
        >
          Cancel
        </button>
      </div>
      {error !== null ? (
        <p className="ask-micro" style={{ color: "var(--alarm)" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
