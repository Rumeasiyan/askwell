"use client";

import { useState } from "react";

import { useCardRef, type LeaderPair } from "@/components/ask/leader";
import { useLiveTurn } from "@/components/ask/ask-state";
import { anchorLabel, pageLabel, recordCardClick, type CitationCard } from "@/lib/citations";

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
          : "Nothing in this answer was cited."}
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-3 p-4" style={{ listStyle: "none" }}>
      {cards.map((card) => (
        <li key={card.chunkId}>
          <SourceCard turnId={turn.id} card={card} />
        </li>
      ))}
    </ul>
  );
}

/** The claim-to-card pairs the live turn's own citations describe, for
 * `LeaderCanvas` (`shell.tsx` renders it once, fed by this) — one pair per
 * claim ordinal a card carries, so two claims on one card draw two lines. */
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

const PASSAGE_TRUNCATE_AT = 220;

function SourceCard({ turnId, card }: { turnId: string; card: CitationCard }) {
  const ref = useCardRef(`${turnId}:${card.chunkId}`);
  const [expanded, setExpanded] = useState(false);

  const label = pageLabel(card) ?? anchorLabel(card);
  const passage = card.passage.trim();
  const isLong = passage.length > PASSAGE_TRUNCATE_AT;
  const shown = expanded || !isLong ? passage : `${passage.slice(0, PASSAGE_TRUNCATE_AT).trimEnd()}…`;

  return (
    <article
      ref={ref}
      className="flex flex-col gap-1.5 p-3"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--rule)",
        borderLeft: "2px solid var(--provenance)",
        borderRadius: "var(--radius)",
      }}
    >
      <a
        href={`/documents/${card.documentId}${card.pageFrom !== null ? `?page=${card.pageFrom}` : ""}`}
        onClick={() => recordCardClick()}
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
      </a>

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
