"use client";

import type { ReactNode } from "react";

import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Rail } from "@/components/shell/rail";
import { StatusBanner } from "@/components/shell/status-banner";
import { useStatus } from "@/lib/use-status";

/**
 * The three-column shell. `docs/ux/design-system.md` §4.
 *
 *   sources 240px | conversation, 68–75ch | provenance 300px
 *
 * **The margin is reserved even when empty.** It is not a popover, a drawer or
 * a toggle — its permanence is what makes an uncited claim visibly wrong: the
 * claim sits in the column with nothing beside it and nothing pointing at it.
 * The layout enforces C4 rather than trusting the model to. Collapsing it when
 * empty would remove exactly the signal it exists to give.
 *
 * Askwell is a desktop application, so there is no phone. The breakpoints here
 * serve a resized window on a laptop, which is a normal thing to do. Container
 * queries rather than viewport ones, because when this is hosted in a Tauri
 * window the viewport stops being the thing that changes.
 *
 * The chrome bar is the app's own, not the browser's — M7 puts this inside a
 * Tauri window with no browser chrome at all, and `M0-SHELL-FE-017a` hangs the
 * narrow-window menu control on it.
 */
export function Shell({ children }: { children: ReactNode }) {
  const status = useStatus();

  return (
    <div className="@container flex h-dvh flex-col" style={{ background: "var(--paper)" }}>
      <header
        className="flex shrink-0 items-center justify-between px-3 py-2"
        style={{ borderBottom: "1px solid var(--rule)" }}
      >
        <div className="flex items-center gap-3">
          {/* M0-SHELL-FE-017a attaches the drawer control here. */}
          <span id="askwell-chrome-start" />
          <span style={{ fontSize: "var(--t-ui)" }}>Askwell</span>
          <StatusDot status={status} />
        </div>
        <ThemeToggle />
      </header>

      <div className="flex min-h-0 flex-1">
        <aside
          className="hidden shrink-0 overflow-y-auto @3xl:block"
          style={{ width: "var(--rail)", borderRight: "1px solid var(--rule)" }}
        >
          <Rail />
        </aside>

        <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
          <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-6">
            <StatusBanner status={status} />
            <main className="min-w-0">{children}</main>
          </div>
        </div>

        {/* Reserved, always. Below the breakpoint it stops being a column and
            reflows inline under each answer — never removed, because that
            would make citations conditional on window width. */}
        <aside
          aria-label="Provenance"
          className="hidden shrink-0 overflow-y-auto @5xl:block"
          style={{
            width: "var(--margin-rail)",
            borderLeft: "1px solid var(--rule)",
            background: "var(--surface)",
          }}
        >
          <p className="ask-micro p-4">Sources appear here, beside the claims they support.</p>
        </aside>
      </div>
    </div>
  );
}

function StatusDot({ status }: { status: ReturnType<typeof useStatus> }) {
  const { colour, title } =
    status.kind === "loading"
      ? { colour: "var(--muted)", title: "Checking" }
      : status.kind === "unreachable"
        ? { colour: "var(--alarm)", title: "Askwell is not answering" }
        : status.assistant.available &&
            status.health.components.every((c) => c.state === "reachable")
          ? { colour: "var(--provenance)", title: "Ready" }
          : { colour: "var(--inferred)", title: status.assistant.headline };

  return (
    <span className="flex items-center gap-1.5" title={title}>
      {/* Circular is the one exception to the 3px radius (§4). */}
      <span
        aria-hidden
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: colour,
          display: "inline-block",
        }}
      />
      {/* Colour is never the only signal (§8), so the state is also words. */}
      <span className="ask-micro">{title}</span>
    </span>
  );
}
