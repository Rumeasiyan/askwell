"use client";

import type { Reachability } from "@/lib/health";
import { label } from "@/lib/health";

/**
 * What state Askwell is in, said plainly.
 *
 * Three rules from `docs/states-and-edge-cases.md` §1 and `M0-MODEL-BE-020`:
 *
 * Askwell not answering and the assistant not answering are different things
 * with different fixes, and must never be collapsed into one message.
 *
 * When health cannot be read, say so. Rendering as if healthy because a fetch
 * failed is a lie told at the exact moment it matters most.
 *
 * An unavailable assistant is not a broken product. What still works is
 * stated, because the instinct on reading "unavailable" is to assume nothing
 * does.
 *
 * There is deliberately no offline warning. Being offline is the design point.
 */
export function StatusBanner({ status }: { status: Reachability }) {
  if (status.kind === "loading") {
    return (
      <Banner tone="muted" heading="Checking…">
        Asking Askwell what state it is in.
      </Banner>
    );
  }

  if (status.kind === "unreachable") {
    return (
      <Banner tone="alarm" heading="Askwell is not running">
        {status.error} The interface is loaded, so something is serving this
        page — but the application behind it is not answering. Start the stack
        with <Code>podman compose up -d</Code>.
      </Banner>
    );
  }

  const { health, assistant } = status;
  const broken = health.components.filter(
    (component) => component.state !== "reachable" && component.component !== "inference",
  );

  // Ordered by what the user can act on first. A missing database is why the
  // assistant is idle, and telling them about the assistant would send them to
  // the wrong place entirely.
  if (broken.length > 0) {
    return (
      <Banner tone="alarm" heading={`${label(broken[0]!.component)} is not available`}>
        {broken[0]!.reason ?? "It is not answering."}{" "}
        {broken.length > 1
          ? `${broken.length - 1} other component${broken.length > 2 ? "s are" : " is"} also affected.`
          : null}
      </Banner>
    );
  }

  if (!assistant.available) {
    return (
      <Banner tone="inferred" heading={assistant.headline}>
        {assistant.fix}
        {assistant.still_works.length > 0 ? (
          <>
            {" "}
            <span style={{ color: "var(--ink)" }}>Still works:</span>{" "}
            {assistant.still_works.join(" · ")}.
          </>
        ) : null}
      </Banner>
    );
  }

  return null;
}

function Banner({
  tone,
  heading,
  children,
}: {
  tone: "muted" | "alarm" | "inferred";
  heading: string;
  children: React.ReactNode;
}) {
  const colour = tone === "muted" ? "var(--muted)" : `var(--${tone})`;
  return (
    <div
      role="status"
      className="ask-carries-meaning px-4 py-3"
      style={{
        background: "var(--surface)",
        borderLeftColor: colour,
        borderRadius: "var(--radius)",
      }}
    >
      <p className="ask-micro" style={{ color: colour }}>
        {heading}
      </p>
      <p className="mt-1" style={{ fontSize: "var(--t-meta)", lineHeight: "var(--t-meta-lh)" }}>
        {children}
      </p>
    </div>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code
      className="px-1"
      style={{ background: "var(--sunk)", borderRadius: "var(--radius)" }}
    >
      {children}
    </code>
  );
}
