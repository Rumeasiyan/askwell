"use client";

import { useHoverHandlers } from "@/components/ask/leader";
import { useWebRaised } from "@/components/ask/web-pairing";
import { retrievedDateLabel, truncatedTitle, truncatedUrl, type WebResult } from "@/lib/web-citations";

/**
 * The web results region, separate from the provenance margin.
 * `M6.5-WEB-FE-190` (`docs/ux/web-search.md` §3, `docs/ux/design-system.md`
 * §7).
 *
 * Never `ProvenanceMargin`'s `<ul>`, never `InlineSourceCards` — this is its
 * own region, meant to render *adjacent to* those, never inside either one,
 * at any width. Nothing in this file imports from `provenance-margin.tsx`
 * and nothing there imports this: the two share no implementation, per the
 * ticket's own "any reuse of the source card component — forbidden."
 *
 * Wired into the live turn by `ask-screen.tsx` (`M6.5-WEB-FE-191`) once a
 * turn actually carries a web citation — this component itself still knows
 * nothing about `AskTurn`, only the results it is handed.
 */
export function WebResultsRegion({
  turnId,
  results,
}: {
  turnId: string;
  results: readonly WebResult[];
}) {
  if (results.length === 0) return null;
  return (
    <section
      aria-label="Web results"
      className="flex flex-col gap-3 p-3"
      style={{
        background: "var(--surface)",
        border: "1px dashed var(--inferred)",
        borderRadius: "var(--radius)",
      }}
    >
      <p className="ask-micro" style={{ color: "var(--inferred)" }}>
        From the web &mdash; not your files
      </p>
      <ul className="flex flex-col gap-3" style={{ listStyle: "none" }}>
        {results.map((result) => (
          <li key={result.url}>
            <WebResultCard turnId={turnId} result={result} />
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * One result. Domain and title in mono (apparatus — `design-system.md` §3),
 * the passage in serif (language), both in `--inferred`/`--muted`, never
 * `--provenance` — that colour is reserved for material the user owns and
 * can open (`design-system.md` §2), which a web page never is.
 *
 * Sized to its own passage — no fixed height, no padding to match a source
 * card's shape, so a one-sentence passage renders at its natural size
 * (the ticket's own edge case).
 *
 * **Raises on hover/focus of its own claim(s), never a document's**
 * (`M6.5-WEB-FE-191`). `useWebRaised`/`useHoverHandlers` are the same shared
 * hover registry `ProvenanceMargin`'s `SourceCard` uses, keyed `web:` so a
 * card key here can never collide with a margin card's `chunkId`-based key —
 * but deliberately *not* `useCardRef`: no leader line is ever drawn to this
 * region (`design-system.md` §7's own "web result is not a variant of
 * source card"), so this never registers into the registry
 * `LeaderCanvas` draws lines from.
 */
function WebResultCard({ turnId, result }: { turnId: string; result: WebResult }) {
  const cardKey = `web:${turnId}:${result.url}`;
  const { onHover, onUnhover } = useHoverHandlers(cardKey);
  const raised = useWebRaised(cardKey);
  const passage = result.passage.trim();
  const title = truncatedTitle(result.title);
  const url = truncatedUrl(result.url);

  return (
    <article
      className="ask-card-raised flex flex-col gap-1.5"
      data-raised={raised}
      onMouseEnter={onHover}
      onMouseLeave={onUnhover}
    >
      <a
        href={result.url}
        target="_blank"
        rel="noopener noreferrer"
        className="ask-navigates flex flex-col gap-0.5 w-fit"
        style={{ color: "var(--ink)" }}
        onFocus={onHover}
        onBlur={onUnhover}
      >
        <span className="ask-micro" style={{ color: "var(--inferred)" }} title={result.domain}>
          {result.domain}
        </span>
        <span className="ask-micro" style={{ textTransform: "none" }} title={result.title}>
          {title}
        </span>
      </a>

      {passage !== "" ? (
        <p className="ask-prose" style={{ fontSize: "var(--t-meta)", lineHeight: "var(--t-meta-lh)" }}>
          &ldquo;{passage}&rdquo;
        </p>
      ) : null}

      <p className="ask-micro flex flex-wrap items-center gap-2" style={{ textTransform: "none" }}>
        <span style={{ color: "var(--muted)" }}>{retrievedDateLabel(result.retrievedAt)}</span>
        <a
          href={result.url}
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: "var(--muted)" }}
          title={result.url}
        >
          {url}
        </a>
      </p>
    </article>
  );
}
