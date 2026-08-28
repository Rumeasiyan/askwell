"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { type AskTurn, useAsk } from "@/components/ask/ask-state";
import { useClaimRef, useHoverHandlers, useScrollToClaim } from "@/components/ask/leader";
import { InlineSourceCards, useRaised } from "@/components/ask/provenance-margin";
import { fetchIngest } from "@/lib/ingest";
import { fetchSuggestions, type Suggestion } from "@/lib/suggestions";
import { segmentClaims } from "@/lib/claims";
import { VERSION } from "@/lib/version";

/** Fills the composer without sending — `ask.md` §4's suggested-follow-up
 * rule applies here too: lowering the cost of the next question is the
 * point, deciding to ask it is not this screen's to make. `scope`, when
 * given, is the context rail's "ask about this source" (`M1-VIEW-FE-048`):
 * the filled question is scoped to one document rather than the whole
 * corpus, until sent or cleared. */
const FILL_COMPOSER_EVENT = "askwell:fill-composer";

export interface ComposerFill {
  question: string;
  scope?: { sourceId: string; filename: string } | null;
}

/**
 * Set the instant this is called, not only carried by the event: the
 * context rail's own "ask about this source" (`M1-VIEW-FE-048`) calls this
 * right before navigating to `/`, and a route change is not synchronous
 * (`shell.tsx`'s `⌘K` shortcut has the same gap) — a listener that only
 * exists once `Composer` mounts would miss the dispatch entirely rather
 * than merely reordering it. `Composer`'s mount effect drains this first,
 * then the event listener covers every later, same-page fill (unchanged
 * from before this ticket, e.g. `SuggestedQuestions`).
 */
let pendingFill: ComposerFill | null = null;

export function fillComposer(question: string, scope: ComposerFill["scope"] = null): void {
  const detail: ComposerFill = { question, scope };
  pendingFill = detail;
  window.dispatchEvent(new CustomEvent<ComposerFill>(FILL_COMPOSER_EVENT, { detail }));
}

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
  const corpus = useCorpusState();
  const { turns } = useAsk();

  return (
    <section className="flex flex-col gap-6">
      {/* Rendered unconditionally, statically — not only inside `FirstRun` —
          so it reaches the exported `index.html` before `corpus` resolves on
          the client. `scripts/check-version.mjs` reads exactly that file for
          exactly this string (`AGENTS.md` §7). */}
      <p className="ask-micro">Askwell {VERSION} · nothing leaves this machine</p>

      {/* `useSearchParams` needs a `Suspense` boundary, and this is the one
          piece of the screen that reads it (`M1-VIEW-FE-048`'s "back to
          answer") — isolated in its own tiny, invisible subtree rather than
          wrapping the whole screen, so the static export still prerenders
          everything above and below this line in full rather than a
          fallback. */}
      <Suspense fallback={null}>
        <ReturnToClaim />
      </Suspense>

      {corpus === "none" ? (
        <FirstRun />
      ) : (
        <>
          <Composer />
          {turns.length === 0 && corpus === "indexing" ? <IndexingNotice /> : null}
          {turns.length === 0 && corpus === "ready" ? <SuggestedQuestions /> : null}
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
 * "Back to answer" from the context rail (`M1-VIEW-FE-048`): `?turn=…&claim=…`
 * names the exact claim the citation supported, and this scrolls to it once
 * the turn (already live in `AskProvider`, above the router) re-renders its
 * `ClaimSpan` here. Cleared from the URL immediately after — a return is a
 * one-time jump, not a state to keep re-applying on every later render or
 * survive a refresh into a claim that may no longer exist.
 */
function ReturnToClaim(): null {
  const searchParams = useSearchParams();
  const router = useRouter();
  const scrollToClaim = useScrollToClaim();
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    const turn = searchParams.get("turn");
    const claim = searchParams.get("claim");
    if (turn === null || claim === null) return;
    handled.current = true;
    scrollToClaim(`${turn}:${claim}`);
    router.replace("/");
  }, [searchParams, router, scrollToClaim]);

  return null;
}

type CorpusState = "none" | "indexing" | "ready" | null;

/**
 * Three states, not two (`ask.md` §5's own edge case): nothing added yet,
 * something added but nothing askable yet, and something actually
 * searchable. `null` while that is still being found out, so neither the
 * first-run card nor the suggestion state flashes in ahead of a real answer.
 * Reuses `fetchIngest` (`M1-ADD-ING-025`) rather than a new endpoint — a
 * source's own `askable` flag already answers "is there one indexed
 * document", one call away.
 */
function useCorpusState(): CorpusState {
  const [corpus, setCorpus] = useState<CorpusState>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchIngest()
      .then((state) => {
        if (cancelled) return;
        if (state.sources.length === 0) setCorpus("none");
        else setCorpus(state.sources.some((source) => source.askable) ? "ready" : "indexing");
      })
      .catch(() => {
        // Unreachable is `StatusBanner`'s job to say, loudly, above this
        // screen. Here it only decides which state to show, and guessing
        // "ready" is the safer of the three — it still lets someone type a
        // question once the assistant comes back, rather than steering them
        // toward adding a source they already have.
        if (!cancelled) setCorpus("ready");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return corpus;
}

/**
 * Sources exist, none are indexed yet (`ask.md` §5, `states-and-edge-cases.md`
 * §7's own edge case: "a corpus with sources but none indexed yet — the
 * suggestion state says so rather than suggesting questions nothing can
 * answer"). Never a spinner with no words — the composer above still works,
 * once retrieval actually has something to search.
 */
function IndexingNotice() {
  return (
    <p className="ask-prose" style={{ color: "var(--muted)" }}>
      Still indexing what you added. Questions will search it once at least one file is ready —
      check the{" "}
      <Link href="/library/" className="ask-navigates">
        library
      </Link>{" "}
      for progress.
    </p>
  );
}

/**
 * Up to three questions named from what was actually ingested — real
 * filenames, real headings, real terms (`ask.md` §5, `first-run.md` §6,
 * both settled: no model call, generated from what ingestion already
 * extracted). Fewer than three shown rather than padded with anything
 * generic if the corpus cannot support three (`M1-LIB-FE-051`'s own edge
 * case). Clicking fills the composer; it does not send — the same rule
 * `conversation.md` §3 gives suggested follow-ups after an answer.
 */
function SuggestedQuestions() {
  const [suggestions, setSuggestions] = useState<Suggestion[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchSuggestions()
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

  if (suggestions === null || suggestions.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      <p className="ask-micro">From what you have added</p>
      <ul className="flex flex-col gap-1 list-none p-0">
        {suggestions.map((suggestion) => (
          <li key={suggestion.question}>
            <button
              type="button"
              onClick={() => fillComposer(suggestion.question)}
              className="ask-navigates ask-prose text-left px-0"
              style={{ background: "none", border: "none" }}
            >
              {suggestion.question}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
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
  const [scope, setScope] = useState<{ sourceId: string; filename: string } | null>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    textarea.current?.focus();
    const onFocusRequest = (): void => textarea.current?.focus();
    window.addEventListener("askwell:focus-composer", onFocusRequest);
    return () => window.removeEventListener("askwell:focus-composer", onFocusRequest);
  }, []);

  useEffect(() => {
    const apply = (detail: ComposerFill): void => {
      setValue(detail.question);
      setScope(detail.scope ?? null);
      textarea.current?.focus();
    };
    if (pendingFill !== null) {
      apply(pendingFill);
      pendingFill = null;
    }
    const onFill = (event: Event): void => {
      pendingFill = null;
      apply((event as CustomEvent<ComposerFill>).detail);
    };
    window.addEventListener(FILL_COMPOSER_EVENT, onFill);
    return () => window.removeEventListener(FILL_COMPOSER_EVENT, onFill);
  }, []);

  const submit = (): void => {
    if (value.trim() === "") return;
    ask(value, scope?.sourceId ?? null);
    setValue("");
    setScope(null);
  };

  return (
    <div className="flex flex-col gap-2">
      {scope !== null ? (
        <p className="ask-micro flex items-center gap-2">
          Scoped to {scope.filename}
          <button
            type="button"
            onClick={() => setScope(null)}
            className="ask-navigates px-0"
            style={{ background: "none", border: "none" }}
          >
            Clear
          </button>
        </p>
      ) : null}
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

      {/* Below the three-column breakpoint the margin `<aside>` is
          CSS-hidden (`shell.tsx`) — these are the same cards, inline,
          never removed. `hidden @5xl:block` there, so this is its mirror:
          shown below the breakpoint, hidden at width. `M1-CITE-FE-044`. */}
      {turn.citations.length > 0 ? (
        <div className="block @5xl:hidden">
          <InlineSourceCards turnId={turn.id} cards={turn.citations} />
        </div>
      ) : null}

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

/**
 * Hovering or focusing a claim raises its card(s), and a card hovered or
 * focused raises this claim back (`ProvenanceMargin`'s `SourceCard`,
 * `M1-CITE-FE-044`). `tabIndex={0}` is what makes the second half of that
 * true without a pointer — the ticket's own "keyboard focus produces the
 * same pairing".
 */
function ClaimSpan({
  turnId,
  ordinal,
  children,
}: {
  turnId: string;
  ordinal: number;
  children: ReactNode;
}) {
  const claimKey = `${turnId}:${ordinal}`;
  const ref = useClaimRef(claimKey);
  const { onHover, onUnhover } = useHoverHandlers(claimKey);
  const raised = useRaised(claimKey);
  return (
    <span
      ref={ref}
      data-claim-ordinal={ordinal}
      data-raised={raised}
      tabIndex={0}
      className="ask-claim-raised"
      onMouseEnter={onHover}
      onMouseLeave={onUnhover}
      onFocus={onHover}
      onBlur={onUnhover}
    >
      {children}
    </span>
  );
}
