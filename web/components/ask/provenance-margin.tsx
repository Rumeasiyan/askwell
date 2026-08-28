"use client";

import Link from "next/link";
import { useState } from "react";

import { useCardRef, useHoveredKey, useHoverHandlers, type LeaderPair } from "@/components/ask/leader";
import { useLiveTurn } from "@/components/ask/ask-state";
import { anchorLabel, documentHref, pageLabel, recordCardClick, type CitationCard } from "@/lib/citations";
import { isAbstained } from "@/lib/ask";
import { isRaised } from "@/lib/pairing";

/**
 * The permanent right-hand margin's contents. `M1-CITE-FE-043`.
 *
 * Rendered inside `ShellFrame`'s own `<aside aria-label="Provenance">`
 * (`shell.tsx`), which is what makes it present in every state — this
 * component only ever decides what fills that reserved space, never whether
 * the space itself exists.
 */
export function ProvenanceMargin() {
  const turn = useLiveTurn();
  const cards = turn?.citations ?? [];

  if (turn === null || cards.length === 0) {
    return (
      <p className="ask-micro p-4">
        {turn === null
          ? "Sources appear here, beside the claims they support."
          : isAbstained(turn)
            ? // The margin's own explicit empty state for abstention
              // (`ask.md` §6, `M2-ABSTAIN-FE-055`): named as empty because
              // nothing matched, not left to read the same as an ordinary
              // uncited answer.
              "No sources — nothing in your files matched."
            : "Nothing in this answer was cited."}
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-3 p-4" style={{ listStyle: "none" }}>
      {cards.map((card) => (
        <li key={card.chunkId}>
          <SourceCard turnId={turn.id} card={card} variant="margin" />
        </li>
      ))}
    </ul>
  );
}

/**
 * The same cards, inline beneath an answer, for the width below the
 * three-column breakpoint (`shell.tsx`'s margin `<aside>` is CSS-hidden
 * there). `M1-CITE-FE-044` — rendered unconditionally, hidden by CSS rather
 * than by React, so it never depends on a JS breakpoint read; visibility is
 * `.ask-inline-cards` (`ask-screen.tsx`'s `Turn`), matching the margin
 * `<aside>`'s own `hidden @5xl:block` pattern in reverse.
 */
export function InlineSourceCards({ turnId, cards }: { turnId: string; cards: CitationCard[] }) {
  if (cards.length === 0) return null;
  return (
    <ul className="flex flex-col gap-3" style={{ listStyle: "none" }}>
      {cards.map((card) => (
        <li key={card.chunkId}>
          <SourceCard turnId={turnId} card={card} variant="inline" />
        </li>
      ))}
    </ul>
  );
}

/** The claim-to-card pairs the live turn's own citations describe, for
 * `LeaderCanvas` (`shell.tsx` renders it once, fed by this) — one pair per
 * claim ordinal a card carries, so two claims on one card draw two lines.
 * Also the pairing data hover-raise reads (`useRaised` below) — the same
 * pairs answer both "where does the line go" and "what should raise
 * together", so this stays the one place that computes them. */
export function useLiveLeaderPairs(): { pairs: LeaderPair[]; active: boolean } {
  const turn = useLiveTurn();
  if (turn === null) return { pairs: [], active: false };
  const pairs: LeaderPair[] = turn.citations.flatMap((card) =>
    card.claimOrdinals.map((ordinal) => ({
      claimKey: `${turn.id}:${ordinal}`,
      cardKey: `${turn.id}:${card.chunkId}`,
    })),
  );
  return { pairs, active: turn.status === "running" };
}

/**
 * Whether `key` (a claim key or a card key) should be shown raised right
 * now — either it is itself hovered/focused, or it is paired with whatever
 * is. `M1-CITE-FE-044`: hovering a claim raises exactly its card(s), and
 * hovering a card raises exactly its claim(s), including the "two cards for
 * one claim" case, since every matching pair is checked.
 */
export function useRaised(key: string): boolean {
  const hovered = useHoveredKey();
  const { pairs } = useLiveLeaderPairs();
  return isRaised(key, hovered, pairs);
}

const PASSAGE_TRUNCATE_AT = 220;

/**
 * `variant` decides only the left edge's token and whether the card
 * registers into the leader-line registry. At width the leader line is what
 * joins a claim to its card, so the edge is decorative `--provenance`
 * (`design-system.md` §7). Below the breakpoint there is no leader, so the
 * edge itself carries that relationship and takes `--rule-strong` — the
 * same token the leader uses, per this ticket and §2/§8's contrast table.
 * An inline card does not call `useCardRef`: no leader is ever drawn to it,
 * so registering a DOM node for it would only let a hidden, zero-size
 * inline node clobber the margin card's real position in the registry.
 */
function SourceCard({
  turnId,
  card,
  variant,
}: {
  turnId: string;
  card: CitationCard;
  variant: "margin" | "inline";
}) {
  const cardKey = `${turnId}:${card.chunkId}`;
  const marginRef = useCardRef(variant === "margin" ? cardKey : "");
  const { onHover, onUnhover } = useHoverHandlers(cardKey);
  const raised = useRaised(cardKey);
  const [expanded, setExpanded] = useState(false);

  const label = pageLabel(card) ?? anchorLabel(card);
  const passage = card.passage.trim();
  const isLong = passage.length > PASSAGE_TRUNCATE_AT;
  const shown = expanded || !isLong ? passage : `${passage.slice(0, PASSAGE_TRUNCATE_AT).trimEnd()}…`;
  const edgeToken = variant === "margin" ? "var(--provenance)" : "var(--rule-strong)";

  return (
    <article
      ref={variant === "margin" ? marginRef : undefined}
      className="ask-card-raised flex flex-col gap-1.5 p-3"
      data-raised={raised}
      onMouseEnter={onHover}
      onMouseLeave={onUnhover}
      style={{
        background: "var(--surface)",
        border: "1px solid var(--rule)",
        borderLeft: `2px solid ${edgeToken}`,
        borderRadius: "var(--radius)",
      }}
    >
      <Link
        // A plain `<a>` here would reload the whole application on click,
        // which is fatal to the context rail's "back to answer": the live
        // turn (`AskProvider`, above the router in `shell.tsx`) only
        // survives a *client-side* route change. `M1-VIEW-FE-048`.
        href={documentHref(card, { turnId, claimOrdinal: card.claimOrdinals[0]! })}
        onClick={() => recordCardClick()}
        onFocus={onHover}
        onBlur={onUnhover}
        className="ask-navigates flex flex-col gap-0.5"
        style={{ color: "var(--ink)" }}
      >
        <span className="ask-micro" style={{ color: "var(--provenance)" }}>
          {card.filename}
          {label !== null ? ` · ${label}` : ""}
        </span>
        <span
          className="ask-prose"
          style={{ fontSize: "var(--t-meta)", lineHeight: "var(--t-meta-lh)" }}
        >
          &ldquo;{shown}&rdquo;
        </span>
      </Link>

      {isLong ? (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="ask-micro w-fit"
          style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}
        >
          {expanded ? "Show less" : "See full passage"}
        </button>
      ) : null}
    </article>
  );
}
