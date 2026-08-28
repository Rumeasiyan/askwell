/**
 * The shape half of "a word plus a shape, never colour alone"
 * (`docs/ux/design-system.md` §8). The word is always the adjacent label —
 * this is `aria-hidden`, decorative reinforcement, not the only carrier of
 * the fact.
 *
 * Four distinct forms, not four tints of the same dot: a hollow ring reads
 * differently from a filled one even in greyscale or to a colour-blind eye,
 * which four circles in four hues would not.
 */
export function StatusMark({ status }: { status: string }) {
  const common = { width: 10, height: 10, viewBox: "0 0 10 10", "aria-hidden": true } as const;

  if (status === "ready") {
    return (
      <svg {...common}>
        <circle cx="5" cy="5" r="4" fill="var(--ink)" />
      </svg>
    );
  }
  if (status === "indexing") {
    return (
      <svg {...common}>
        <circle cx="5" cy="5" r="4" fill="none" stroke="var(--muted)" strokeWidth="1.5" />
        <path d="M5 1 A4 4 0 0 1 9 5 L5 5 Z" fill="var(--muted)" />
      </svg>
    );
  }
  if (status === "attention") {
    return (
      <svg {...common}>
        <path d="M5 0.5 L9.5 9 L0.5 9 Z" fill="var(--alarm)" />
      </svg>
    );
  }
  // queued, and anything not yet named — the honest "nothing has happened" mark.
  return (
    <svg {...common}>
      <circle
        cx="5"
        cy="5"
        r="4"
        fill="none"
        stroke="var(--muted)"
        strokeWidth="1.5"
        strokeDasharray="2 2"
      />
    </svg>
  );
}
