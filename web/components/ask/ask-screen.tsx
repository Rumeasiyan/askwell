"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { type AskTurn, useAsk } from "@/components/ask/ask-state";
import { useClaimRef, useHoverHandlers, useScrollToClaim } from "@/components/ask/leader";
import { InlineSourceCards, useRaised } from "@/components/ask/provenance-margin";
import {
  isConflict,
  isPartial,
  parseAnswerAnnotations,
  recordConflictPresented,
} from "@/lib/answer-annotations";
import type { CitationCard } from "@/lib/citations";
import { CONVERSATION_PAGE_SIZE, conversationWindow, dividerLabel, liveTurnId,
  isAbstained,
  isFirstAnswer,
} from "@/lib/ask";
import { documentHref, pageLabel } from "@/lib/citations";
import { followUpSuggestions, recordFollowUpUsed } from "@/lib/follow-ups";
import { fetchIngest } from "@/lib/ingest";
import { fetchSearch, type SearchHit } from "@/lib/search";
import { fetchSuggestions, type Suggestion } from "@/lib/suggestions";
import { segmentClaims } from "@/lib/claims";
import { useStatus } from "@/lib/use-status";
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
 * here, on purpose: abstention's own rendering (`M2`). Since `M1-CITE-FE-043`,
 * `LiveTurn` wraps each cited claim in a span the provenance margin's leader
 * can find (`ProvenanceMargin`, `shell.tsx`) — the margin itself lives
 * there, not here, since it is a sibling column, not a child of this screen.
 *
 * Since `M1-CONV-FE-178`, only one turn (`liveTurnId`, `lib/ask.ts`) renders
 * this way; every other turn is either still `queued` (its own tiny
 * placeholder) or collapses to a question, a stored summary and a source
 * count (`CollapsedTurn`, `docs/ux/conversation.md` §2). Time dividers
 * (`conversation.md` §4) are computed between consecutive turns, not stored
 * — `dividerLabel` is pure precisely so this list can be a plain map with no
 * effect recomputing anything as the clock ticks over.
 */
export function AskScreen() {
  const corpus = useCorpusState();
  const { turns } = useAsk();
  const liveId = liveTurnId(turns);
  const status = useStatus();
  // `status.kind === "loading"` renders neither state rather than flashing
  // the search panel in for the instant before the first poll resolves —
  // the same reason `useCorpusState` starts at `null` (`ask.md` §5's own
  // edge case: nothing should assume the worse of two states before it
  // actually knows).
  const assistantDown = status.kind === "reporting" && !status.assistant.available;

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
          {assistantDown ? <DegradedSearch /> : null}
          <Composer />
          {turns.length === 0 && corpus === "indexing" ? <IndexingNotice /> : null}
          {turns.length === 0 && corpus === "ready" ? <SuggestedQuestions /> : null}
          {turns.length > 0 ? <TurnList turns={turns} liveId={liveId} /> : null}
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

/**
 * The turn list with paging (`conversation.md` §5, §7; `M1-CONV-FE-179`).
 *
 * Every turn already lives in `AskProvider`'s own state — there is no reload
 * of a past conversation yet (issue number 156: `conversation_id` is not
 * threaded across turns, so nothing survives a refresh to page a request
 * against) — so "paging in on scroll" here means revealing more of that same
 * in-memory list, oldest last, never a network call that could fail. `revealed` counts
 * back from the newest turn (`conversationWindow`, `lib/ask.ts`); scrolling
 * the boundary row into view grows it by one more page.
 */
function TurnList({ turns, liveId }: { turns: AskTurn[]; liveId: string | null }) {
  const [revealed, setRevealed] = useState(CONVERSATION_PAGE_SIZE);
  const { turns: windowed, hasMore } = conversationWindow(turns, revealed);
  const boundaryRef = useRef<HTMLDivElement>(null);
  const revealMore = () => setRevealed((count) => count + CONVERSATION_PAGE_SIZE);

  useEffect(() => {
    if (!hasMore) return;
    const node = boundaryRef.current;
    if (node === null) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) revealMore();
      },
      { rootMargin: "200px 0px 0px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasMore]);

  return (
    <div className="flex flex-col gap-4">
      {turns.length > CONVERSATION_PAGE_SIZE ? (
        <div ref={boundaryRef} className="flex justify-center py-2">
          {hasMore ? (
            <button
              type="button"
              onClick={revealMore}
              className="ask-navigates ask-micro px-3 py-1"
              style={{ border: "1px solid var(--rule)" }}
            >
              Load earlier turns
            </button>
          ) : (
            <p className="ask-micro">Start of this conversation</p>
          )}
        </div>
      ) : null}

      {windowed.map((turn, index) => {
        const previous = windowed[index - 1];
        const label =
          previous !== undefined ? dividerLabel(previous.createdAt, turn.createdAt) : null;
        return (
          <div key={turn.id} className="flex flex-col gap-4">
            {label !== null ? <TurnDivider label={label} /> : null}
            <TurnRow turn={turn} live={turn.id === liveId} />
          </div>
        );
      })}
    </div>
  );
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
 * Search across sources, offered the moment the assistant is unavailable
 * (`docs/states-and-edge-cases.md` §1 "Model not loaded", `ask.md` §5,
 * `M2-FAIL-FE-060`). `StatusBanner` (`shell.tsx`) already says the assistant
 * is down and how to fix it, above every screen — this is Ask's own half of
 * the ticket: retrieval does not need the model, so a keyword search still
 * works, and this is where it is actually offered rather than only promised
 * in `Assistant.still_works`' own prose.
 *
 * Reads `useStatus()` a second time rather than threading a prop down from
 * `Shell` — `ShellFrame` renders `children` with no status prop today
 * (`shell.tsx`), and duplicating one cheap poll of a local, single-user
 * process is a smaller change than plumbing status through every route.
 * Because it is the same hook, the panel disappears the moment the assistant
 * reports ready again — `AskScreen`'s next render simply stops mounting it,
 * which is what makes "recovers without a reload" true for free.
 */
function DegradedSearch() {
  const [query, setQuery] = useState("");
  const [state, setState] = useState<
    | { kind: "idle" }
    | { kind: "loading" }
    | { kind: "done"; keywordOnly: boolean; hits: SearchHit[] }
    | { kind: "failed"; error: string }
  >({ kind: "idle" });

  const submit = (event: React.FormEvent): void => {
    event.preventDefault();
    const trimmed = query.trim();
    if (trimmed === "") return;
    setState({ kind: "loading" });
    void fetchSearch(trimmed)
      .then((result) => setState({ kind: "done", keywordOnly: result.keywordOnly, hits: result.results }))
      .catch((error: unknown) =>
        setState({
          kind: "failed",
          error: error instanceof Error ? error.message : "Search failed.",
        }),
      );
  };

  return (
    <div
      className="flex flex-col gap-3 px-4 py-3"
      style={{ background: "var(--surface)", border: "1px solid var(--rule)", borderRadius: "var(--radius)" }}
    >
      <p className="ask-micro">Search your files while the assistant is unavailable</p>
      <form onSubmit={submit} className="flex gap-2">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search by keyword"
          className="ask-input ask-prose flex-1 px-3 py-2"
          aria-label="Search your documents"
        />
        <button
          type="submit"
          disabled={query.trim() === ""}
          className="ask-action-primary px-4"
          style={{ fontSize: "var(--t-ui)", opacity: query.trim() === "" ? 0.5 : 1 }}
        >
          Search
        </button>
      </form>

      {state.kind === "loading" ? <p className="ask-micro">Searching…</p> : null}

      {state.kind === "failed" ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          {state.error}
        </p>
      ) : null}

      {state.kind === "done" ? (
        <>
          {/* `keywordOnly` (`lib/search.ts`): dense search needs the model to
              embed the query, so when the assistant is down every match here
              is lexical alone — the ticket's own edge case names this
              explicitly rather than letting a keyword-only result set look
              like an ordinary ranked search. */}
          {state.keywordOnly ? (
            <p className="ask-micro">Keyword-only while the assistant is unavailable.</p>
          ) : null}
          {state.hits.length === 0 ? (
            <p className="ask-prose" style={{ color: "var(--muted)" }}>
              Nothing in your files matched that search.
            </p>
          ) : (
            <ul className="flex flex-col gap-3 list-none p-0">
              {state.hits.map((hit) => (
                <SearchHitRow key={hit.chunkId} hit={hit} />
              ))}
            </ul>
          )}
        </>
      ) : null}
    </div>
  );
}

function SearchHitRow({ hit }: { hit: SearchHit }) {
  const page = pageLabel(hit);
  const href = documentHref({
    chunkId: hit.chunkId,
    documentId: hit.documentId,
    filename: hit.filename,
    anchorKind: hit.anchorKind,
    heading: hit.heading,
    pageFrom: hit.pageFrom,
    pageTo: hit.pageTo,
    passage: hit.passage,
    quotedSpan: null,
    claimOrdinals: [],
  });

  return (
    <li className="flex flex-col gap-1">
      <a href={href} className="ask-navigates ask-prose">
        {hit.filename}
        {page !== null ? ` · ${page}` : ""}
      </a>
      <p className="ask-prose" style={{ color: "var(--muted)" }}>
        {hit.passage}
      </p>
    </li>
  );
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

/**
 * Up to three suggestions derived from the answer just given
 * (`conversation.md` §3, `M1-CONV-FE-180`). `followUpSuggestions`
 * (`lib/follow-ups.ts`) is what decides content and count — none for an
 * abstained turn, fewer than three rather than padded — this only renders
 * whatever it returned, or nothing at all. Clicking fills the composer via
 * the same `fillComposer` the pre-question suggestions and the context
 * rail's "ask about this source" already use; it never sends.
 */
/**
 * The one celebratory moment, said once.
 *
 * `docs/ux/first-run.md` §4: the citation is the product, and somebody reading
 * their first answer does not yet know the margin beside it can be clicked. The
 * wizard already says so before the question is sent, which is a promise about
 * something not yet seen; this says it while the citation is actually on
 * screen, which is the only moment it teaches anything.
 *
 * Only for a first answer that cited something. An abstention is the right
 * answer and has its own treatment, but it is not the moment to celebrate a
 * margin that is empty.
 */
function FirstAnswerNote({ turn }: { turn: AskTurn }) {
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (turn.citations.length === 0) return;
    const controller = new AbortController();
    let live = true;
    void isFirstAnswer(controller.signal).then((first) => {
      if (live) setShow(first);
    });
    return () => {
      live = false;
      controller.abort();
    };
  }, [turn.citations.length]);

  if (!show) return null;

  return (
    <p className="ask-micro" style={{ color: "var(--provenance)" }}>
      That is your first answer — and beside it is where it came from. Every claim Askwell
      makes names the document and page behind it, and you can open a source to read the
      passage yourself.
    </p>
  );
}


function FollowUpSuggestions({ turn }: { turn: AskTurn }) {
  const suggestions = useMemo(() => followUpSuggestions(turn), [turn]);
  if (suggestions.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      <p className="ask-micro">Follow up</p>
      <ul className="flex flex-col gap-1 list-none p-0">
        {suggestions.map((question) => (
          <li key={question}>
            <button
              type="button"
              onClick={() => {
                recordFollowUpUsed();
                fillComposer(question);
              }}
              className="ask-navigates ask-prose text-left px-0"
              style={{ background: "none", border: "none" }}
            >
              {question}
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
  // Read by `apply` below, whose listener effect has an empty dependency
  // list and would otherwise close over the composer's very first, empty
  // `value` forever — the same stale-closure fix `AskProvider`'s `current`
  // ref applies for the same reason.
  const valueRef = useRef(value);

  useEffect(() => {
    valueRef.current = value;
  }, [value]);

  useEffect(() => {
    textarea.current?.focus();
    const onFocusRequest = (): void => textarea.current?.focus();
    window.addEventListener("askwell:focus-composer", onFocusRequest);
    return () => window.removeEventListener("askwell:focus-composer", onFocusRequest);
  }, []);

  useEffect(() => {
    // A suggestion (this ticket, `M1-CONV-FE-180`, and the pre-question
    // corpus suggestions before it) must not silently destroy a draft
    // already in progress — the ticket's own edge case. An empty composer
    // fills without asking; a non-empty one asks first, and declining
    // leaves the draft exactly as it was.
    const apply = (detail: ComposerFill): void => {
      if (valueRef.current.trim() !== "" && !window.confirm("Replace your draft with this suggestion?")) {
        return;
      }
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

/**
 * A simple hairline with its label (`conversation.md` §4) — decorative, so
 * `--rule` (`design-system.md` §2's own contrast table), never `--provenance`
 * or `--ink`. Purely visual grouping: nothing below it depends on the label
 * having rendered, `dividerLabel` (`lib/ask.ts`) already decided that.
 */
function TurnDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3" role="separator" aria-label={label}>
      <span className="ask-micro" style={{ whiteSpace: "nowrap" }}>
        {label}
      </span>
      <span aria-hidden="true" style={{ flex: 1, borderTop: "1px solid var(--rule)" }} />
    </div>
  );
}

/**
 * One turn, in whichever of the three shapes `conversation.md` §2/§5
 * describes applies to it right now: still `queued` behind another answer,
 * the one live turn, or collapsed. `live` comes from `liveTurnId` in the
 * parent rather than being recomputed here, so every row in the list agrees
 * on which single turn is full without each one re-deriving it.
 */
function TurnRow({ turn, live }: { turn: AskTurn; live: boolean }) {
  if (live) return <LiveTurn turn={turn} />;
  if (turn.status === "queued") return <QueuedTurn turn={turn} />;
  return <CollapsedTurn turn={turn} />;
}

/**
 * A turn waiting behind the one actually streaming (`conversation.md` §5:
 * "queued, not interleaved"). Never collapsed — collapsing shows a stored
 * summary and source count, and this turn has neither yet.
 */
function QueuedTurn({ turn }: { turn: AskTurn }) {
  return (
    <article className="flex flex-col gap-1">
      <p className="ask-prose" style={{ color: "var(--muted)" }}>
        {turn.question}
      </p>
      <p className="ask-micro">Waiting for the question ahead of it.</p>
    </article>
  );
}

/**
 * A past turn, shrunk to one scannable line (`conversation.md` §2): the
 * question in full (CSS-truncated, never wrapped — `.ask-collapsed-line`),
 * the stored one-line summary, and the source count. `--provenance` belongs
 * to the count alone here — nothing else in this row spends it
 * (`design-system.md` §2's "reserved" note, and this ticket's own validation
 * rule).
 *
 * Clicking the row expands it in place with its stored answer and margin,
 * restoring exactly what was recorded — never re-run against a changed
 * corpus (`conversation.md` §6). Its own `expanded` state, not lifted to
 * `AskScreen`: each turn is its own component instance keyed by `turn.id`,
 * so "expanding one turn collapses nothing else" falls out for free rather
 * than needing a set of ids tracked anywhere. `M1-CONV-FE-179`.
 */
function CollapsedTurn({ turn }: { turn: AskTurn }) {
  const [expanded, setExpanded] = useState(false);
  const marginRef = useRef<HTMLDivElement>(null);
  const scrollPending = useRef(false);

  useEffect(() => {
    if (!expanded || !scrollPending.current) return;
    scrollPending.current = false;
    marginRef.current?.scrollIntoView({ block: "center" });
  }, [expanded]);

  const toggle = (): void => setExpanded((value) => !value);

  const expandAndScrollToMargin = (): void => {
    if (expanded) {
      marginRef.current?.scrollIntoView({ block: "center" });
      return;
    }
    scrollPending.current = true;
    setExpanded(true);
  };

  return (
    <article className="flex flex-col gap-3">
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={toggle}
        onKeyDown={(event) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          toggle();
        }}
        className="flex items-baseline gap-3"
        style={{ cursor: "pointer" }}
      >
        <p
          className="ask-prose ask-collapsed-line"
          style={{ color: "var(--muted)", flex: "0 1 auto", maxWidth: "45%" }}
          title={turn.question}
        >
          {turn.question}
        </p>
        <p className="ask-micro ask-collapsed-line" style={{ textTransform: "none", flex: 1 }}>
          {turn.summary ?? ""}
        </p>
        <SourceCountBadge
          count={turn.sourceCount}
          onClick={turn.sourceCount !== null ? expandAndScrollToMargin : undefined}
        />
      </div>

      {expanded ? (
        <div className="flex flex-col gap-2">
          {isAbstained(turn) ? <AbstentionState turn={turn} /> : null}
          {!isAbstained(turn) && turn.answer !== "" ? <AnsweredContent turn={turn} /> : null}
          {turn.status === "failed" && turn.reason !== null ? (
            <p className="ask-prose" style={{ color: "var(--muted)" }}>
              {turn.reason}
            </p>
          ) : null}
          {/* Every expanded past turn gets its own margin, right here — the
              shared `<aside>` (`ProvenanceMargin`, `shell.tsx`) only ever
              shows the live turn's citations, so a second, third, fourth
              expanded turn cannot borrow it without stealing it from
              whichever one is actually streaming. Reusing the inline variant
              unconditionally (`M1-CITE-FE-044`, `design-system.md` §7) rather
              than only below the breakpoint is the deliberate trade-off:
              "over presentation that already exists" (this ticket's own
              granularity note) rather than a second live margin column. */}
          <div ref={marginRef}>
            <InlineSourceCards
              turnId={turn.id}
              cards={turn.citations}
              showDate={isConflict(parseAnswerAnnotations(turn.answer))}
            />
          </div>
          <div>
            <button
              type="button"
              onClick={toggle}
              className="ask-navigates px-3 py-1"
              style={{ border: "1px solid var(--rule-strong)", fontSize: "var(--t-ui)" }}
            >
              Collapse
            </button>
          </div>
        </div>
      ) : null}
    </article>
  );
}

/**
 * The count itself, or the visibly-different "no count" shape a turn that
 * abstained (or failed) shows instead (`conversation.md` §2, §5;
 * `states-and-edge-cases.md` §7.1). Colour is never the only signal
 * (`design-system.md` §8) — a filled dot beside the number versus an open,
 * slashed circle beside "No sources" carries the distinction even in
 * greyscale, and only the answered form spends `--provenance`.
 *
 * `onClick`, when given, is a nested real `<button>` inside the row's own
 * `role="button"` (`CollapsedTurn`) — expanding-and-scrolling is a more
 * specific action than the row's plain toggle, so it needs its own target
 * rather than overloading the row's click with "which part was clicked".
 */
function SourceCountBadge({
  count,
  onClick,
}: {
  count: number | null;
  onClick?: (() => void) | undefined;
}) {
  if (count === null) {
    return (
      <span
        className="ask-micro flex items-center gap-1"
        style={{ textTransform: "none", whiteSpace: "nowrap" }}
      >
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
          <circle cx="5" cy="5" r="4" fill="none" stroke="currentColor" strokeWidth="1.2" />
          <line x1="1.8" y1="8.2" x2="8.2" y2="1.8" stroke="currentColor" strokeWidth="1.2" />
        </svg>
        No sources
      </span>
    );
  }
  const label = `${count} source${count === 1 ? "" : "s"}`;
  const content = (
    <>
      <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
        <circle cx="5" cy="5" r="4" fill="currentColor" />
      </svg>
      {count}
    </>
  );
  const style = {
    color: "var(--provenance)",
    fontSize: "var(--t-micro)",
    letterSpacing: "var(--t-micro-tracking)",
    whiteSpace: "nowrap" as const,
  };
  if (onClick === undefined) {
    return (
      <span className="flex items-center gap-1" style={style} aria-label={label}>
        {content}
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      className="flex items-center gap-1"
      style={{ ...style, background: "none", border: "none", padding: 0, cursor: "pointer" }}
      aria-label={label}
    >
      {content}
    </button>
  );
}

function LiveTurn({ turn }: { turn: AskTurn }) {
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

      {isAbstained(turn) ? <AbstentionState turn={turn} /> : null}

      {!isAbstained(turn) && turn.answer !== "" ? <AnsweredContent turn={turn} /> : null}

      {/* Below the three-column breakpoint the margin `<aside>` is
          CSS-hidden (`shell.tsx`) — these are the same cards, inline,
          never removed. `hidden @5xl:block` there, so this is its mirror:
          shown below the breakpoint, hidden at width. `M1-CITE-FE-044`. */}
      {!isAbstained(turn) && turn.citations.length > 0 ? (
        <div className="block @5xl:hidden">
          <InlineSourceCards
            turnId={turn.id}
            cards={turn.citations}
            showDate={isConflict(parseAnswerAnnotations(turn.answer))}
          />
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

      {turn.status === "completed" ? <FirstAnswerNote turn={turn} /> : null}

      {turn.status === "completed" ? <FollowUpSuggestions turn={turn} /> : null}

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
 * The abstained state (`ask.md` §5/§6, `M2-ABSTAIN-FE-055`). Rendered
 * instead of `AnswerProse`, never alongside it — `isAbstained` (`lib/ask.ts`)
 * is what both `LiveTurn` and `CollapsedTurn` gate on to keep those mutually
 * exclusive.
 *
 * `turn.reason` is the whole composed message
 * (`askwell.agent.abstain.compose_abstention`): the situation on its own
 * line, the proof of search (when there is one to prove), and the next
 * action, `\n`-joined. Split and re-rendered as separate lines rather than
 * left as one block of text so the situation line can carry `--ink` while
 * the rest carries `--muted` (`design-system.md` §2's own abstention rule:
 * "renders in `--ink` and `--muted` with more space than an answer would
 * get" — never `--alarm`, never a caveat). `py-4` is that "more space": an
 * abstention is not squeezed into the same rhythm as a paragraph of prose.
 *
 * `AddSourceAction` sits in its own region below every line of that message,
 * on purpose: `ask.md`'s own note that this ticket's shape is what
 * `M6.5-WEB-FE-186` later adds two siblings beside, and that nothing may
 * render above the abstention statement (C10). Until that ticket, this
 * region holds exactly one control.
 */
function AbstentionState({ turn }: { turn: AskTurn }) {
  const lines = (turn.reason ?? "").split("\n").filter((line) => line !== "");

  return (
    <div className="flex flex-col gap-6 py-4">
      <div className="flex flex-col gap-2">
        {lines.map((line, index) => (
          <p
            key={index}
            className="ask-prose"
            style={{ color: index === 0 ? "var(--ink)" : "var(--muted)" }}
          >
            {line}
          </p>
        ))}
      </div>
      <div>
        <AddSourceAction question={turn.question} />
      </div>
    </div>
  );
}

/**
 * The abstained state's own next action (`ask.md` §5/§6, scope's own
 * "add-a-source action wired to the add flow with the question retained").
 * Mirrors `AskAboutSource` (`context-rail.tsx`, `M1-VIEW-FE-048`) exactly:
 * `fillComposer` before the navigation, not after — the route change is not
 * synchronous, and its module-level slot (`ask-screen.tsx`'s own
 * `pendingFill`) is what survives the gap. `Composer` drains it the moment
 * it remounts on the way back to `/`, so the question the user just asked is
 * sitting in the composer, ready to re-ask, the moment the newly added
 * source is in.
 */
function AddSourceAction({ question }: { question: string }) {
  const router = useRouter();

  const addSource = (): void => {
    fillComposer(question);
    router.push("/sources/add/");
  };

  return (
    <button
      type="button"
      onClick={addSource}
      className="ask-navigates px-4 py-2"
      style={{ border: "1px solid var(--rule-strong)", fontSize: "var(--t-ui)" }}
    >
      Add a source
    </button>
  );
}

/**
 * The answered body of a non-abstained turn: the prose, the partial and
 * conflicting-sources states layered on top of it, never in place of it.
 * `M2-PARTIAL-FE-058`.
 *
 * `parseAnswerAnnotations` reads the "Not covered:" and "Conflicting
 * sources on ...:" lines back out of `turn.answer` — the same convention
 * `askwell.agent.partial`/`conflict` read server-side (`lib/answer-annotations.ts`'s
 * own docstring) — and `cleanedText` is what `AnswerProse` renders instead
 * of the raw answer, so those fixed label lines become their own distinct
 * elements rather than unstyled prose sitting in the middle of the answer.
 * The cited position sentences a conflict presents stay in `cleanedText`
 * unchanged: they carry `[n]` markers and belong in the normal claim flow,
 * feeding the same provenance margin every other citation does.
 */
function AnsweredContent({ turn }: { turn: AskTurn }) {
  const annotations = useMemo(() => parseAnswerAnnotations(turn.answer), [turn.answer]);
  const conflict = isConflict(annotations);
  const partial = isPartial(annotations);

  return (
    <div className="flex flex-col gap-3">
      {conflict ? <ConflictBanner topic={annotations.conflictTopic!} /> : null}
      {annotations.cleanedText !== "" ? (
        <AnswerProse turnId={turn.id} text={annotations.cleanedText} />
      ) : null}
      {partial ? <UncoveredBlock items={annotations.uncovered} /> : null}
      {conflict ? <ResolveOffer topic={annotations.conflictTopic!} citations={turn.citations} /> : null}
    </div>
  );
}

/**
 * "Conflicting sources on X" — the heading `docs/ux/ask.md` §5 asks for,
 * distinguishing this state from an ordinary answer before the reader
 * reaches the two positions themselves. `--ink`, not `--alarm`: a real
 * conflict is not an error state, matching the abstention rule's own
 * reasoning (`AbstentionState`, above) against colouring an honest product
 * state as a failure.
 *
 * Fires the local, untransmitted conflicts-presented counter
 * (`recordConflictPresented`, ticket's own Analytics Events line) exactly
 * once per turn: mounted only once `conflictTopic` first resolves out of
 * the streaming text and never remounted while that stays true, so a
 * re-render mid-stream cannot double-count it.
 */
function ConflictBanner({ topic }: { topic: string }) {
  useEffect(() => {
    recordConflictPresented();
  }, []);

  return (
    <p className="ask-micro" style={{ textTransform: "none", color: "var(--ink)" }}>
      Conflicting sources on {topic}
    </p>
  );
}

/**
 * The ungrounded part of a partial answer, visually distinct from the
 * answered part above it (`docs/ux/ask.md` §5's own acceptance criterion) —
 * a rule, not a colour: `--muted` text behind a `--rule-strong` left edge,
 * the same contrast device `SourceCard`'s own left edge uses for "this is
 * apparatus, not prose the model asserted".
 */
function UncoveredBlock({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div
      className="flex flex-col gap-1 py-1"
      style={{ borderLeft: "2px solid var(--rule-strong)", paddingLeft: "0.75rem" }}
    >
      <p className="ask-micro">Not covered by your files</p>
      {items.map((item, index) => (
        <p key={index} className="ask-prose" style={{ color: "var(--muted)" }}>
          {item}
        </p>
      ))}
    </div>
  );
}

/**
 * The resolve offer (`docs/ux/ask.md` §5, this ticket's own scope line: "an
 * offer to resolve which writes a memory fact once memory exists in M3.
 * Until then the offer records the user's choice as a pending resolution
 * and says so"). Options are the turn's own cited documents — the same
 * dates and citations the reader just weighed — never a re-typed summary
 * of each position, since the card above already stated it with a
 * citation.
 *
 * Client-only state, not sent anywhere (C1): there is nothing to write yet
 * (`askwell.agent.conflict`'s own `memory_fact` hook is inert until M3), so
 * the honest interface is a choice that is remembered for this turn, in
 * this tab, and says plainly that it does not survive past that.
 */
function ResolveOffer({ topic, citations }: { topic: string; citations: CitationCard[] }) {
  const [resolvedChunkId, setResolvedChunkId] = useState<string | null>(null);
  const resolved = citations.find((card) => card.chunkId === resolvedChunkId) ?? null;

  if (resolved !== null) {
    return (
      <p className="ask-micro" style={{ textTransform: "none" }}>
        Noted {resolved.filename} as current for {topic}. This is not saved yet — Askwell
        will remember it once memory ships.
      </p>
    );
  }

  if (citations.length < 2) return null;

  return (
    <div className="flex flex-col gap-2">
      <p className="ask-micro" style={{ textTransform: "none" }}>
        Which one is current?
      </p>
      <div className="flex flex-wrap gap-2">
        {citations.map((card) => (
          <button
            key={card.chunkId}
            type="button"
            onClick={() => setResolvedChunkId(card.chunkId)}
            className="ask-navigates px-3 py-1"
            style={{ border: "1px solid var(--rule-strong)", fontSize: "var(--t-ui)" }}
          >
            {card.filename}
          </button>
        ))}
      </div>
    </div>
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
