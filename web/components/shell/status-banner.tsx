"use client";

import { useSyncExternalStore } from "react";

import type { Reachability } from "@/lib/health";
import { label } from "@/lib/health";

/**
 * `M7-PACK-FE-143`'s repair surface, reachable from here — `docs/ux/ask.md`
 * §5 "Model unavailable" names this banner as the link point. It is a
 * button, not a link: the surface is a second native window
 * (`web/src-tauri/shell-assets/supervision.html`), opened through the one
 * Tauri command granted to this window for it
 * (`allow-open-supervision-window`, `capabilities/default.json`), not a URL.
 *
 * Only rendered inside the Tauri shell — a plain-browser visit to this same
 * page (the API served over an ordinary tab, with no shell supervising
 * anything) has nothing for it to open, and `window.__TAURI_INTERNALS__`
 * existing is what tells the two apart. Checked in an effect rather than at
 * module scope so this still renders identically during server-side
 * rendering (`window` does not exist there) before hydration corrects it.
 * `useSyncExternalStore` rather than a mount-effect: the value never changes
 * within a session, so there is nothing to subscribe to — this is the
 * documented way to read an external, browser-only value without a
 * setState-in-effect (flagged by this repo's `eslint-plugin-react-hooks`).
 */
function inShellSubscribe(): () => void {
  return () => {};
}

function inShellSnapshot(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

function inShellServerSnapshot(): boolean {
  return false;
}

function SupervisionButton() {
  const inShell = useSyncExternalStore(inShellSubscribe, inShellSnapshot, inShellServerSnapshot);

  if (!inShell) return null;

  return (
    <button
      type="button"
      onClick={() => {
        const internals = (window as unknown as { __TAURI_INTERNALS__: { invoke: (cmd: string) => Promise<unknown> } })
          .__TAURI_INTERNALS__;
        void internals.invoke("open_supervision_window");
      }}
      className="mt-2"
      style={{
        font: "inherit",
        fontSize: "var(--t-meta)",
        padding: "0.3rem 0.7rem",
        borderRadius: "var(--radius)",
        border: "1px solid var(--rule)",
        background: "var(--surface)",
        color: "var(--ink)",
        cursor: "pointer",
      }}
    >
      Open Supervision…
    </button>
  );
}

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
        <SupervisionButton />
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
        <SupervisionButton />
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
