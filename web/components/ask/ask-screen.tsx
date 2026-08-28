"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { type AskTurn, useAsk } from "@/components/ask/ask-state";
import { useClaimRef } from "@/components/ask/leader";
import { fetchIngest } from "@/lib/ingest";
import { segmentClaims } from "@/lib/claims";
import { VERSION } from "@/lib/version";

/**
 * The Ask screen. `docs/ux/ask.md`, `M1-ASK-FE-039`.
 *
 * Composer, the live turn, streaming and step labels — the three states this
 * ticket owns (`ask.md` §5: retrieving, streaming, answered). What is not
 * here, on purpose: abstention's own rendering (`M2`), and collapsing past
 * turns (`M1-CONV-FE-180`) — every turn here simply stacks. Since
 * `M1-CITE-FE-043`, `Turn` wraps each cited claim in a span the provenance
 * margin's leader can find (`ProvenanceMargin`, `shell.tsx`) — the margin
 * itself lives there, not here, since it is a sibling column, not a child of
 * this screen.
 */
export function AskScreen() {
  const hasSources = useHasSources();
  const { turns } = useAsk();

  return (
    <section className="flex flex-col gap-6">
      {/* Rendered unconditionally, statically — not only inside `FirstRun` —
          so it reaches the exported `index.html` before `hasSources` resolves
          on the client. `scripts/check-version.mjs` reads exactly that file
          for exactly this string (`AGENTS.md` §7). */}
      <p className="ask-micro">Askwell {VERSION} · nothing leaves this machine</p>

      {hasSources === false ? (
        <FirstRun />
      ) : (
        <>
          <Composer />
          {turns.length > 0 ? (
            <div className="flex flex-col gap-8">
              {turns.map((turn) => (
                <Turn key={turn.id} turn={turn} />
              ))}
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

/**
 * Whether any source has ever been recorded on this machine — `null` while
 * that is still being found out, so the first-run card never flashes in
 * ahead of a real answer. Reuses `fetchIngest` (`M1-ADD-ING-025`) rather than
 * a new endpoint; a source's coverage list is exactly "does anything exist",
 * one call away, and this ticket adds no backend of its own.
 */
function useHasSources(): boolean | null {
  const [hasSources, setHasSources] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchIngest()
      .then((state) => {
        if (!cancelled) setHasSources(state.sources.length > 0);
      })
      .catch(() => {
        // Unreachable is `StatusBanner`'s job to say, loudly, above this
        // screen. Here it only decides which of two states to show, and
        // guessing "no sources" is the safer of two guesses — it still lets
        // someone type a question once the assistant comes back.
        if (!cancelled) setHasSources(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return hasSources;
}

function FirstRun() {
  return (
    <section className="flex flex-col gap-4">
      <h1 style={{ fontSize: "var(--t-display)", lineHeight: "var(--t-display-lh)" }}>
        Ask your own material
      </h1>

      <p className="ask-prose">
        Askwell answers from documents and databases you have added, and cites what it
        used. When nothing in your material answers a question, it says so instead of
        guessing — which is the whole reason it is worth pointing at a confidential
        corpus.
      </p>

      <div
        className="flex flex-col gap-2 px-4 py-3"
        style={{
          background: "var(--surface)",
          border: "1px solid var(--rule)",
          borderRadius: "var(--radius)",
        }}
      >
        <p className="ask-micro">Nothing added yet</p>
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          There is nothing to ask about until you add a source. Drop files or a folder
          anywhere on this window — you do not have to go anywhere first — or add them from
          the screen below.
        </p>
        <div>
          <Link
            href="/sources/add/"
            className="ask-navigates inline-block px-4 py-2"
            style={{ border: "1px solid var(--rule-strong)", fontSize: "var(--t-ui)" }}
          >
            Add a source
          </Link>
        </div>
      </div>
    </section>
  );
}

/**
 * Type, `Enter` submits, `Shift+Enter` newlines (`ask.md` §4). Never disabled
 * while a turn streams — the whole point of the queue in `AskProvider` is
 * that a question asked mid-answer still lands rather than being refused.
 */
function Composer() {
  const { ask } = useAsk();
  const [value, setValue] = useState("");
  const textarea = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    textarea.current?.focus();
    const onFocusRequest = (): void => textarea.current?.focus();
    window.addEventListener("askwell:focus-composer", onFocusRequest);
    return () => window.removeEventListener("askwell:focus-composer", onFocusRequest);
  }, []);

  const submit = (): void => {
    if (value.trim() === "") return;
    ask(value);
    setValue("");
  };

  return (
    <div className="flex flex-col gap-2">
      <textarea
        ref={textarea}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
        placeholder="Ask about your own files and databases"
        rows={3}
        className="ask-input ask-prose w-full px-3 py-2"
        style={{ resize: "none" }}
        aria-label="Ask a question"
      />
      <div className="flex justify-end items-center gap-2">
        <MicControl />
        <button
          type="button"
          onClick={submit}
          disabled={value.trim() === ""}
          className="ask-action-primary px-4"
          style={{ fontSize: "var(--t-ui)", opacity: value.trim() === "" ? 0.5 : 1 }}
        >
          Ask
        </button>
      </div>
    </div>
  );
}

const MIC_REASON = "Voice arrives with the voice release. Type for now.";

/**
 * Present from Phase 1, disabled with its reason (`ask.md` §4, `M1-ASK-FE-039a`).
 * No audio work of any kind: no `getUserMedia`, no permission request, no
 * transport. `aria-disabled` (not the `disabled` attribute) keeps the button
 * focusable so a screen reader announces it — disabled with its reason —
 * rather than skipping past an unlabelled dead stop. `voice.md` §2 fixes its
 * final position (in the composer, beside send) so M6 changes state, not
 * geometry.
 */
function MicControl() {
  return (
    <span className="ask-mic-wrap">
      <button
        type="button"
        aria-disabled="true"
        aria-describedby="ask-mic-reason"
        className="ask-mic-control"
      >
        <MicIcon />
        <span className="ask-sr-only">Voice input</span>
      </button>
      <span role="tooltip" id="ask-mic-reason" className="ask-mic-reason">
        {MIC_REASON}
      </span>
    </span>
  );
}

function MicIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      aria-hidden="true"
    >
      <rect x="5.5" y="1.5" width="5" height="8" rx="2.5" />
      <path d="M3 8.5a5 5 0 0 0 10 0" strokeLinecap="round" />
      <path d="M8 13.5v1.5" strokeLinecap="round" />
    </svg>
  );
}

function Turn({ turn }: { turn: AskTurn }) {
  const { running, stop } = useAsk();
  const isRunning = turn.status === "running";
  const isStreaming = isRunning && turn.answer !== "";
  const isRetrieving = isRunning && turn.answer === "";

  return (
    <article className="flex flex-col gap-2" aria-busy={isRunning}>
      <p className="ask-prose" style={{ color: "var(--muted)" }}>
        {turn.question}
      </p>

      {turn.status === "queued" ? (
        <p className="ask-micro">Waiting for the question ahead of it.</p>
      ) : null}

      {/* Named steps, before the first token and kept visible alongside it —
          apparatus, so mono (`design-system.md` §3). */}
      {turn.steps.length > 0 && (isRetrieving || isStreaming) ? (
        <p className="ask-micro" aria-live="polite">
          {turn.steps.map((step) => step.label).join(" · ")}
        </p>
      ) : null}

      {turn.answer !== "" ? <AnswerProse turnId={turn.id} text={turn.answer} /> : null}

      {turn.status === "failed" && turn.reason !== null ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          {turn.reason}
        </p>
      ) : null}

      {turn.status === "stopped" ? (
        <p className="ask-micro">Stopped. The answer above is partial.</p>
      ) : null}

      {isRunning && running?.id === turn.id ? (
        <div>
          <button
            type="button"
            onClick={stop}
            className="ask-navigates px-3 py-1"
            style={{ border: "1px solid var(--rule-strong)", fontSize: "var(--t-ui)" }}
          >
            Stop
          </button>
        </div>
      ) : null}
    </article>
  );
}

/**
 * The answer, with every cited claim wrapped in a span the provenance
 * margin's leader can point at. `M1-CITE-FE-043`.
 *
 * `segmentClaims` (`lib/claims.ts`) mirrors the server's own claim
 * numbering exactly, so a `citation` event's `claim_ordinal` names the same
 * sentence here that it named in `askwell.agent.claims.segment_claims` —
 * re-run on every render rather than incrementally, the same "recompute
 * against the growing prefix" approach the server itself uses, and just as
 * cheap at answer length.
 */
function AnswerProse({ turnId, text }: { turnId: string; text: string }) {
  const claims = useMemo(() => segmentClaims(text), [text]);

  const nodes: ReactNode[] = [];
  let cursor = 0;
  for (const claim of claims) {
    if (claim.start > cursor) nodes.push(text.slice(cursor, claim.start));
    nodes.push(
      <ClaimSpan key={`claim-${claim.ordinal}`} turnId={turnId} ordinal={claim.ordinal}>
        {claim.text}
        {claim.terminator}
      </ClaimSpan>,
    );
    cursor = claim.end;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));

  return <p className="ask-prose">{nodes}</p>;
}

function ClaimSpan({
  turnId,
  ordinal,
  children,
}: {
  turnId: string;
  ordinal: number;
  children: ReactNode;
}) {
  const ref = useClaimRef(`${turnId}:${ordinal}`);
  return (
    <span ref={ref} data-claim-ordinal={ordinal}>
      {children}
    </span>
  );
}
