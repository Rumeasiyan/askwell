"use client";

/**
 * The provider key: enter, replace, remove. `M8-KEY-FE-174`,
 * `docs/ux/settings.md` §3.
 *
 * The server never returns the key (`askwell.online.key_status`), so the set
 * state is the provider it is for and nothing else. The key lives in a
 * password field from the paste until the save returns, and the field is
 * emptied then. What each action does to online conversations is stated
 * beside its button, before it is pressed. Each action is a decisions record
 * on the server, naming the provider only (`M8-KEY-BE-173`).
 *
 * A passphrase set and not yet entered means a new key cannot be encrypted,
 * so the form asks for the passphrase first rather than failing at Save.
 * Removing needs no passphrase: deleting the key decrypts nothing.
 */

import { useEffect, useState } from "react";

import {
  entryProblem,
  fetchKeyStatus,
  KEY_UNSET,
  KeyLocked,
  keySetLine,
  LOCKED_FIRST,
  REMOVE_CONSEQUENCE,
  REMOVED,
  removeKey,
  REPLACE_CONSEQUENCE,
  REPLACED,
  SAVED,
  storeKey,
  type KeyStatus,
} from "@/lib/online-key";
import { fetchPassphraseStatus, unlockPassphrase } from "@/lib/passphrase";

const FIELD = { border: "1px solid var(--rule)", padding: "0.25rem 0.5rem" } as const;
const BUTTON = { border: "1px solid var(--rule)" } as const;

function message(thrown: unknown, fallback: string): string {
  return thrown instanceof Error ? thrown.message : fallback;
}

export function OnlineKey() {
  const [status, setStatus] = useState<KeyStatus | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchKeyStatus(controller.signal)
      .then(setStatus)
      .catch((thrown: unknown) => {
        if (!controller.signal.aborted) setFailure(message(thrown, "Askwell could not read whether a key is set."));
      });
    return () => controller.abort();
  }, []);

  const remove = (): void => {
    setRemoving(true);
    setError(null);
    void removeKey()
      .then((next) => {
        setStatus(next);
        setNotice(REMOVED);
      })
      .catch((thrown: unknown) => setError(message(thrown, "Askwell could not remove the key.")))
      .finally(() => setRemoving(false));
  };

  if (failure !== null) {
    return (
      <p className="ask-micro" style={{ textTransform: "none", color: "var(--alarm)" }}>
        {failure}
      </p>
    );
  }
  if (status === null) {
    return (
      <p className="ask-prose" style={{ color: "var(--muted)" }}>
        Reading…
      </p>
    );
  }

  if (editing) {
    return (
      <KeyForm
        current={status}
        onSaved={(next, replaced) => {
          setStatus(next);
          setEditing(false);
          setNotice(replaced ? REPLACED : SAVED);
        }}
        onCancel={() => setEditing(false)}
      />
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="ask-prose">{status.set ? keySetLine(status.provider) : KEY_UNSET}</p>
      {status.set ? (
        <>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setNotice(null);
                setEditing(true);
              }}
              disabled={removing}
              className="ask-navigates px-2 py-1"
              style={BUTTON}
            >
              Replace the key
            </button>
            <button type="button" onClick={remove} disabled={removing} className="ask-navigates px-2 py-1" style={BUTTON}>
              {removing ? "Removing…" : "Remove the key"}
            </button>
          </div>
          <p className="ask-micro" style={{ textTransform: "none", color: "var(--muted)" }}>
            {REMOVE_CONSEQUENCE}
          </p>
        </>
      ) : (
        <div>
          <button
            type="button"
            onClick={() => {
              setNotice(null);
              setEditing(true);
            }}
            className="ask-navigates px-2 py-1"
            style={BUTTON}
          >
            Add a key
          </button>
        </div>
      )}
      {notice !== null ? (
        <p className="ask-micro" role="status" style={{ textTransform: "none" }}>
          {notice}
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

function KeyForm({
  current,
  onSaved,
  onCancel,
}: {
  current: KeyStatus;
  onSaved: (status: KeyStatus, replaced: boolean) => void;
  onCancel: () => void;
}) {
  // `null` while the passphrase status is being read.
  const [locked, setLocked] = useState<boolean | null>(null);
  const [passphrase, setPassphrase] = useState("");
  // The provider is not secret, so replacing starts from the one held.
  const [destination, setDestination] = useState(current.provider?.destination ?? "");
  const [model, setModel] = useState(current.provider?.model ?? "");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchPassphraseStatus(controller.signal)
      .then((next) => setLocked(next.locked))
      // Unknown is treated as unlocked: the save's own 423 brings the
      // passphrase prompt back if it was wrong.
      .catch(() => {
        if (!controller.signal.aborted) setLocked(false);
      });
    return () => controller.abort();
  }, []);

  const cancel = (): void => {
    setApiKey("");
    setPassphrase("");
    onCancel();
  };

  const unlock = (): void => {
    setBusy(true);
    setError(null);
    void unlockPassphrase(passphrase)
      .then(() => {
        setPassphrase("");
        setLocked(false);
      })
      .catch((thrown: unknown) => setError(message(thrown, "Askwell could not unlock.")))
      .finally(() => setBusy(false));
  };

  const save = (): void => {
    const problem = entryProblem(destination, model, apiKey);
    if (problem !== null) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    void storeKey(destination, model, apiKey)
      .then((next) => {
        setApiKey("");
        onSaved(next, current.set);
      })
      .catch((thrown: unknown) => {
        if (thrown instanceof KeyLocked) setLocked(true);
        setError(message(thrown, "Askwell could not save the key."));
      })
      .finally(() => setBusy(false));
  };

  if (locked === null) {
    return (
      <p className="ask-prose" style={{ color: "var(--muted)" }}>
        Reading…
      </p>
    );
  }

  if (locked) {
    return (
      <div className="flex flex-col gap-2">
        <p className="ask-prose">{LOCKED_FIRST}</p>
        <input
          type="password"
          value={passphrase}
          onChange={(event) => setPassphrase(event.target.value)}
          placeholder="Passphrase"
          aria-label="Passphrase"
          autoComplete="current-password"
          style={FIELD}
        />
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={passphrase.length === 0 || busy}
            onClick={unlock}
            className="ask-navigates px-2 py-1"
            style={BUTTON}
          >
            {busy ? "Unlocking…" : "Unlock"}
          </button>
          <button type="button" disabled={busy} onClick={cancel} className="px-2 py-1" style={{ ...BUTTON, color: "var(--muted)" }}>
            Cancel
          </button>
        </div>
        {error !== null ? (
          <p className="ask-micro" style={{ textTransform: "none", color: "var(--alarm)" }}>
            {error}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <label className="ask-micro flex flex-col gap-1" style={{ textTransform: "none" }}>
        Provider address
        <input
          type="text"
          value={destination}
          onChange={(event) => setDestination(event.target.value)}
          placeholder="api.example.com:443"
          autoComplete="off"
          spellCheck={false}
          style={FIELD}
        />
      </label>
      <label className="ask-micro flex flex-col gap-1" style={{ textTransform: "none" }}>
        Model
        <input
          type="text"
          value={model}
          onChange={(event) => setModel(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          style={FIELD}
        />
      </label>
      <label className="ask-micro flex flex-col gap-1" style={{ textTransform: "none" }}>
        {current.set ? "New key" : "Key"}
        <input
          type="password"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          style={FIELD}
        />
      </label>
      {current.set ? (
        <p className="ask-micro" style={{ textTransform: "none", color: "var(--muted)" }}>
          {REPLACE_CONSEQUENCE}
        </p>
      ) : null}
      <div className="flex items-center gap-2">
        <button type="button" disabled={busy} onClick={save} className="ask-navigates px-2 py-1" style={BUTTON}>
          {busy ? "Saving…" : current.set ? "Replace the key" : "Save the key"}
        </button>
        <button type="button" disabled={busy} onClick={cancel} className="px-2 py-1" style={{ ...BUTTON, color: "var(--muted)" }}>
          Cancel
        </button>
      </div>
      {error !== null ? (
        <p className="ask-micro" role="alert" style={{ textTransform: "none", color: "var(--alarm)" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
