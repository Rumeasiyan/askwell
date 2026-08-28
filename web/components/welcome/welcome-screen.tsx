"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { AddScreen } from "@/components/add/add-screen";
import { fillComposer } from "@/components/ask/ask-screen";
import {
  type ModelDownloadState,
  type SetupState,
  cancelModelDownload,
  decidePassphrase,
  fetchSetupState,
  formatBytes,
  isNoDiskSpaceError,
  skipSetup,
  startModelDownload,
  verifyManualModel,
} from "@/lib/setup";
import { fetchSuggestions, type Suggestion } from "@/lib/suggestions";
import { fetchIngest, type IngestState } from "@/lib/ingest";

type Step = 1 | 2 | 3 | 4;

const STEP_TITLES: Record<Step, string> = {
  1: "What this is",
  2: "Check the machine",
  3: "Get the model",
  4: "Add something and ask",
};

/**
 * The first-run sequence. `docs/ux/first-run.md`.
 *
 * Four steps, always listed, so the end is in sight from the first screen —
 * the ticket's own reason this exists: "install-to-first-answer is the
 * metric most likely to kill the product quietly."
 *
 * Step 3 embeds the real `AddScreen` rather than a summary of it — sources
 * can be added while the model downloads (`docs/ux/first-run.md` §2's "3 —
 * Get the model"), and the working add flow already exists; duplicating it
 * here would be a second, thinner copy that could drift from the first.
 */
export function WelcomeScreen() {
  const [step, setStep] = useState<Step>(1);
  const [setup, setSetup] = useState<SetupState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const router = useRouter();

  const tier = setup?.profile.tier ?? "standard";

  const refresh = useCallback(async () => {
    try {
      const next = await fetchSetupState(tier);
      setSetup(next);
      setLoadError(null);
    } catch (error) {
      setLoadError(String(error));
    }
  }, [tier]);

  useEffect(() => {
    // Deferred rather than called straight away, matching `use-status.ts`'s
    // own reasoning: `refresh` resolves into `setState`, and starting it
    // synchronously inside the effect is what `react-hooks/set-state-in-effect`
    // objects to. A zero timeout is still immediate to a person.
    const id = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(id);
  }, [refresh]);

  // Poll while a download is actually moving. Stops otherwise, so an idle
  // welcome screen left open in a background tab does not poll forever.
  useEffect(() => {
    if (setup?.model.status !== "downloading" && setup?.model.status !== "verifying") {
      return;
    }
    const id = setInterval(() => void refresh(), 1000);
    return () => clearInterval(id);
  }, [setup?.model.status, refresh]);

  if (loadError !== null && setup === null) {
    return (
      <section className="flex flex-col gap-4">
        <h1 style={{ fontSize: "var(--t-display)", lineHeight: "var(--t-display-lh)" }}>
          Welcome to Askwell
        </h1>
        <p className="ask-prose" style={{ color: "var(--alarm)" }}>
          Askwell is not answering right now: {loadError}
        </p>
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 style={{ fontSize: "var(--t-display)", lineHeight: "var(--t-display-lh)" }}>
            Welcome to Askwell
          </h1>
          <p className="ask-micro mt-1">A personal AI over your own files, on this machine.</p>
        </div>
        <button
          type="button"
          onClick={() => {
            void skipSetup().finally(() => router.push("/"));
          }}
          className="ask-navigates px-3 py-1"
          style={{ border: "1px solid var(--rule)", fontSize: "var(--t-meta)" }}
        >
          Skip setup
        </button>
      </header>

      <StepList current={step} />

      {step === 1 ? <StepWhatThisIs onContinue={() => setStep(2)} /> : null}
      {step === 2 && setup !== null ? (
        <StepMachineCheck
          setup={setup}
          onDecidedPassphrase={() => void refresh()}
          onContinue={() => setStep(3)}
        />
      ) : null}
      {step === 3 && setup !== null ? (
        <StepModel
          tier={tier}
          model={setup.model}
          onChanged={() => void refresh()}
          onContinue={() => setStep(4)}
        />
      ) : null}
      {step === 4 ? <StepAsk modelReady={setup?.model.status === "ready"} /> : null}
    </section>
  );
}

function StepList({ current }: { current: Step }) {
  return (
    <ol className="flex flex-wrap gap-3 list-none p-0">
      {([1, 2, 3, 4] as Step[]).map((n) => (
        <li
          key={n}
          className="flex items-center gap-1.5"
          style={{
            fontSize: "var(--t-meta)",
            color: n === current ? "var(--ink)" : "var(--muted)",
            fontWeight: n === current ? 600 : 400,
          }}
        >
          <span
            aria-hidden
            className="flex items-center justify-center"
            style={{
              width: 18,
              height: 18,
              borderRadius: "50%",
              border: `1px solid ${n <= current ? "var(--rule-strong)" : "var(--rule)"}`,
              background: n < current ? "var(--rule-strong)" : "transparent",
              color: n < current ? "var(--paper)" : "inherit",
              fontSize: "11px",
            }}
          >
            {n}
          </span>
          {STEP_TITLES[n]}
        </li>
      ))}
    </ol>
  );
}

function StepWhatThisIs({ onContinue }: { onContinue: () => void }) {
  return (
    <div className="flex flex-col gap-4">
      <p className="ask-prose">
        Askwell reads your files and answers questions about them, on this machine. Nothing
        is uploaded. It asks when it cannot work something out.
      </p>
      <p className="ask-prose">
        <strong>It works offline.</strong> There is no server this depends on.
      </p>
      <p className="ask-prose">
        <strong>Your files stay where they are.</strong> Askwell indexes in place — it does
        not copy your library.
      </p>
      <div>
        <button type="button" onClick={onContinue} className="ask-action-primary px-4">
          Get started
        </button>
      </div>
    </div>
  );
}

function StepMachineCheck({
  setup,
  onDecidedPassphrase,
  onContinue,
}: {
  setup: SetupState;
  onDecidedPassphrase: () => void;
  onContinue: () => void;
}) {
  const { profile } = setup;
  return (
    <div className="flex flex-col gap-4">
      <div
        className="flex flex-col gap-2 px-5 py-4"
        style={{
          background: "var(--surface)",
          border: "1px solid var(--rule)",
          borderRadius: "var(--radius)",
        }}
      >
        <p style={{ fontSize: "var(--t-ui)" }}>{profile.expectation}</p>
        {!profile.floor_met ? (
          <p className="ask-micro" style={{ color: "var(--inferred)" }}>
            This is below what Askwell is built for. It will still run — nothing is refused —
            but expect it to be slow.
          </p>
        ) : null}
        {profile.source === "fallback" ? (
          <p className="ask-micro">
            Askwell could not read this machine&apos;s hardware directly, so it is using its
            standard assumptions instead.
          </p>
        ) : null}
      </div>

      {!setup.passphrase_offered ? (
        <PassphraseOffer onDecided={onDecidedPassphrase} />
      ) : null}

      <div>
        <button type="button" onClick={onContinue} className="ask-action-primary px-4">
          Continue
        </button>
      </div>
    </div>
  );
}

function PassphraseOffer({ onDecided }: { onDecided: () => void }) {
  const [busy, setBusy] = useState<"enable" | "skip" | null>(null);

  function decide(enabled: boolean, which: "enable" | "skip"): void {
    setBusy(which);
    void decidePassphrase(enabled).finally(() => {
      setBusy(null);
      onDecided();
    });
  }

  return (
    <div
      className="flex flex-col gap-2 px-5 py-4"
      style={{
        background: "var(--sunk)",
        border: "1px solid var(--rule)",
        borderRadius: "var(--radius)",
      }}
    >
      <p style={{ fontSize: "var(--t-ui)" }}>Set a passphrase?</p>
      <p className="ask-prose">
        Encrypts your library, so a stolen laptop is not a data breach. You can skip this —
        without it, anyone with access to this machine can read what Askwell has indexed.
        Encryption at rest is not enforced yet, so this only records your preference for now.
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={busy !== null}
          onClick={() => decide(true, "enable")}
          className="ask-action-primary px-3 py-1"
          style={{ fontSize: "var(--t-ui)" }}
        >
          {busy === "enable" ? "Saving…" : "Set a passphrase"}
        </button>
        <button
          type="button"
          disabled={busy !== null}
          onClick={() => decide(false, "skip")}
          className="ask-navigates px-3 py-1"
          style={{ border: "1px solid var(--rule)", fontSize: "var(--t-ui)" }}
        >
          {busy === "skip" ? "…" : "Not now"}
        </button>
      </div>
    </div>
  );
}

function StepModel({
  tier,
  model,
  onChanged,
  onContinue,
}: {
  tier: string;
  model: ModelDownloadState;
  onChanged: () => void;
  onContinue: () => void;
}) {
  const [actionError, setActionError] = useState<string | null>(null);
  const [needed, setNeeded] = useState<{ needed: number; free: number } | null>(null);
  const [showManual, setShowManual] = useState(false);
  const [verifying, setVerifying] = useState(false);

  // A rough, honestly-rounded throughput sampled client-side over the last
  // poll interval — the API reports bytes, not a rate, and this is the same
  // "never an estimate nobody measured" discipline `lib/ingest.ts` already
  // follows for the ingest queue, applied to the one number it does not
  // give us for free.
  //
  // Ref mutation and `setState` both deferred out of the render body itself
  // (a `setTimeout(0)`, `use-status.ts`'s own pattern): the render-purity
  // rules forbid touching a ref or calling `Date.now()` while rendering, and
  // calling `setState` synchronously inside the effect body trips the
  // separate "no cascading renders" rule.
  const last = useRef<{ bytes: number; at: number } | null>(null);
  const [etaSeconds, setEtaSeconds] = useState<number | null>(null);

  useEffect(() => {
    const id = setTimeout(() => {
      const now = Date.now();
      if (model.status !== "downloading") {
        last.current = null;
        setEtaSeconds(null);
        return;
      }
      if (last.current !== null) {
        const elapsed = (now - last.current.at) / 1000;
        const delta = model.downloaded_bytes - last.current.bytes;
        if (elapsed > 0 && delta > 0) {
          const bytesPerSecond = delta / elapsed;
          const remaining = model.total_bytes - model.downloaded_bytes;
          setEtaSeconds(Math.max(1, Math.round(remaining / bytesPerSecond)));
        }
      }
      last.current = { bytes: model.downloaded_bytes, at: now };
    }, 0);
    return () => clearTimeout(id);
  }, [model.downloaded_bytes, model.status, model.total_bytes]);

  async function start(): Promise<void> {
    setActionError(null);
    setNeeded(null);
    try {
      await startModelDownload(tier);
      onChanged();
    } catch (error) {
      if (isNoDiskSpaceError(error)) {
        setNeeded({ needed: error.needed_bytes, free: error.free_bytes });
      } else {
        setActionError(String(error));
      }
    }
  }

  async function cancel(): Promise<void> {
    await cancelModelDownload(tier);
    onChanged();
  }

  async function verifyManual(): Promise<void> {
    setVerifying(true);
    try {
      await verifyManualModel(tier);
      onChanged();
    } finally {
      setVerifying(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div
        className="flex flex-col gap-3 px-5 py-4"
        style={{
          background: "var(--surface)",
          border: "1px solid var(--rule)",
          borderRadius: "var(--radius)",
        }}
      >
        <p style={{ fontSize: "var(--t-ui)" }}>{model.display_name}</p>

        {model.status === "idle" ? (
          <>
            <p className="ask-prose">
              {formatBytes(model.total_bytes)} to download once. This is the one download
              Askwell makes, and only because you started it.
            </p>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => void start()} className="ask-action-primary px-4">
                Download
              </button>
              <button
                type="button"
                onClick={() => setShowManual((was) => !was)}
                className="ask-navigates px-3 py-1"
                style={{ border: "1px solid var(--rule)", fontSize: "var(--t-ui)" }}
              >
                I already have the file
              </button>
            </div>
          </>
        ) : null}

        {model.status === "downloading" || model.status === "verifying" ? (
          <>
            <ProgressBar fraction={model.fraction} />
            <p className="ask-micro">
              {formatBytes(model.downloaded_bytes)} of {formatBytes(model.total_bytes)}
              {model.status === "verifying"
                ? " — checking the download…"
                : etaSeconds === null
                  ? " — measuring…"
                  : ` — about ${humanDuration(etaSeconds)} left`}
            </p>
            {model.status === "downloading" ? (
              <div>
                <button
                  type="button"
                  onClick={() => void cancel()}
                  className="ask-navigates px-3 py-1"
                  style={{ border: "1px solid var(--rule)", fontSize: "var(--t-ui)" }}
                >
                  Cancel
                </button>
              </div>
            ) : null}
          </>
        ) : null}

        {model.status === "paused" ? (
          <>
            <ProgressBar fraction={model.fraction} />
            <p className="ask-micro">
              Paused at {formatBytes(model.downloaded_bytes)} of {formatBytes(model.total_bytes)}.
              Nothing downloaded so far was lost.
            </p>
            <div>
              <button type="button" onClick={() => void start()} className="ask-action-primary px-4">
                Resume
              </button>
            </div>
          </>
        ) : null}

        {model.status === "failed" ? (
          <>
            <p className="ask-prose" style={{ color: "var(--alarm)" }}>
              {model.error ?? "The download failed."}
            </p>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => void start()} className="ask-action-primary px-4">
                Retry
              </button>
              <button
                type="button"
                onClick={() => setShowManual((was) => !was)}
                className="ask-navigates px-3 py-1"
                style={{ border: "1px solid var(--rule)", fontSize: "var(--t-ui)" }}
              >
                Use a file instead
              </button>
            </div>
          </>
        ) : null}

        {model.status === "ready" ? (
          <p className="ask-prose" style={{ color: "var(--provenance)" }}>
            Ready.
          </p>
        ) : null}

        {actionError !== null ? (
          <p className="ask-micro" style={{ color: "var(--alarm)" }}>
            {actionError}
          </p>
        ) : null}

        {needed !== null ? (
          <p className="ask-micro" style={{ color: "var(--alarm)" }}>
            Not enough disk space: needs {formatBytes(needed.needed)}, this machine has{" "}
            {formatBytes(needed.free)} free. Free up space and try again, or use a manual
            file below.
          </p>
        ) : null}

        {showManual || model.status === "idle" ? (
          <div className="flex flex-col gap-2 mt-1" style={{ borderTop: "1px solid var(--rule)" }}>
            <p className="ask-micro mt-2">
              On a slow or air-gapped connection: download {model.display_name} yourself and
              place it at exactly this path, then verify it —
            </p>
            <code
              className="ask-micro"
              style={{ background: "var(--sunk)", padding: "4px 8px", wordBreak: "break-all" }}
            >
              {model.target_path}
            </code>
            <div>
              <button
                type="button"
                disabled={verifying}
                onClick={() => void verifyManual()}
                className="ask-navigates px-3 py-1"
                style={{ border: "1px solid var(--rule)", fontSize: "var(--t-ui)" }}
              >
                {verifying ? "Checking…" : "Verify the file"}
              </button>
            </div>
          </div>
        ) : null}
      </div>

      <div className="flex flex-col gap-2">
        <p className="ask-micro">
          You do not have to wait — add sources now and they will be ready as soon as the
          model is.
        </p>
        <AddScreen />
      </div>

      <div>
        <button
          type="button"
          disabled={model.status !== "ready"}
          onClick={onContinue}
          className="ask-action-primary px-4"
        >
          Continue
        </button>
      </div>
    </div>
  );
}

function ProgressBar({ fraction }: { fraction: number }) {
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(fraction * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
      style={{
        height: 8,
        borderRadius: "var(--radius)",
        background: "var(--sunk)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          height: "100%",
          width: `${Math.round(fraction * 100)}%`,
          background: "var(--provenance)",
          transition: "width 300ms ease",
        }}
      />
    </div>
  );
}

function StepAsk({ modelReady }: { modelReady: boolean | undefined }) {
  const router = useRouter();
  const [suggestions, setSuggestions] = useState<Suggestion[] | null>(null);
  const [ingest, setIngest] = useState<IngestState | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchIngest()
      .then((state) => {
        if (!cancelled) setIngest(state);
      })
      .catch(() => {
        if (!cancelled) setIngest(null);
      });
    fetchSuggestions()
      .then((result) => {
        if (!cancelled) setSuggestions(result);
      })
      .catch(() => {
        if (!cancelled) setSuggestions([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const hasSources = (ingest?.documents_ingested ?? 0) > 0;

  if (!modelReady) {
    return (
      <p className="ask-prose">
        Almost there — go back and finish downloading the model before asking a question.
      </p>
    );
  }

  if (!hasSources) {
    return (
      <p className="ask-prose">
        Ready. Add something to ask about — the previous step&apos;s add box is still open above,
        or open <code>Add a source</code> any time from the rail.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="ask-prose">
        Ready. Here is a question drawn from what you just added — every answer names exactly
        where it came from, and that citation is the point.
      </p>
      {suggestions !== null && suggestions.length > 0 ? (
        <ul className="flex flex-col gap-1 list-none p-0">
          {suggestions.map((suggestion) => (
            <li key={suggestion.question}>
              <button
                type="button"
                onClick={() => {
                  fillComposer(suggestion.question);
                  router.push("/");
                }}
                className="ask-action-primary px-4 py-2 text-left"
                style={{ display: "block" }}
              >
                {suggestion.question}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <div>
          <button type="button" onClick={() => router.push("/")} className="ask-action-primary px-4">
            Ask a question
          </button>
        </div>
      )}
    </div>
  );
}

function humanDuration(seconds: number): string {
  if (seconds < 90) return `${seconds} seconds`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} minutes`;
  return `${Math.round(minutes / 60)} hours`;
}
