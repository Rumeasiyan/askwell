"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { AddProvider } from "@/components/add/add-state";
import { AskProvider } from "@/components/ask/ask-state";
import { LeaderCanvas, LeaderProvider } from "@/components/ask/leader";
import { ProvenanceMargin, useLiveLeaderPairs } from "@/components/ask/provenance-margin";
import { DropTarget } from "@/components/add/drop-target";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Rail } from "@/components/shell/rail";
import { RailDrawer } from "@/components/shell/rail-drawer";
import { StatusBanner } from "@/components/shell/status-banner";
import { fetchIngest } from "@/lib/ingest";
import { fetchSetupState } from "@/lib/setup";
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
 *
 * The add queue is provided here rather than by the add-source screen, because
 * dropping files works anywhere in the application (`M1-ADD-FE-022`). A drop
 * onto Ask navigates to `/sources/add/`, and a queue owned by that screen
 * would be created *by* that navigation — always empty, every time.
 */
export function Shell({ children }: { children: ReactNode }) {
  const status = useStatus();
  useAskShortcut();
  useWelcomeGate();

  return (
    <AddProvider>
      <AskProvider>
        <LeaderProvider>
          <ShellFrame status={status}>{children}</ShellFrame>
        </LeaderProvider>
      </AskProvider>
    </AddProvider>
  );
}

/**
 * `/welcome` — shown until a first source is indexed, then never again
 * (`docs/ux/first-run.md` §"Route"). Checked once per load rather than on
 * every navigation: a source finishing mid-session must not yank someone off
 * whatever screen they are actually looking at, only decide where a *fresh*
 * load lands.
 */
function useWelcomeGate(): void {
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (pathname === "/welcome") return;
    let cancelled = false;

    Promise.all([fetchIngest(), fetchSetupState("standard")])
      .then(([ingest, setup]) => {
        if (cancelled) return;
        const neverIndexed = ingest.documents_ingested === 0;
        if (neverIndexed && !setup.welcome_skipped) {
          router.replace("/welcome");
        }
      })
      .catch(() => {
        // Askwell not answering yet, or `/setup`/`/ingest` failed: stay put
        // rather than bouncing someone into a screen that will fail the same
        // way. The ordinary status banner already says Askwell is down.
      });

    return () => {
      cancelled = true;
    };
    // Intentionally only on first mount: see docstring above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

/**
 * `⌘K` (or `Ctrl+K`) from anywhere reaches the Ask screen (`ask.md` §"Entry
 * points", this ticket's own Scope: "keyboard entry to the screen from
 * anywhere"). Lives here rather than on the Ask screen itself because the
 * whole point is that it works from any route, and a listener owned by a page
 * component is gone the moment that page is not the one mounted.
 *
 * A route change is not synchronous, so the composer this focuses may not
 * exist in the DOM yet the instant `push` returns — `Composer` listens for
 * the same event and attaches its own handler on mount, so whichever comes
 * second (the navigation finishing, or this dispatch) is the one that
 * actually focuses it.
 */
function useAskShortcut(): void {
  const router = useRouter();

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key.toLowerCase() !== "k" || !(event.metaKey || event.ctrlKey)) return;
      event.preventDefault();
      router.push("/");
      window.dispatchEvent(new Event("askwell:focus-composer"));
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [router]);
}

function ShellFrame({
  status,
  children,
}: {
  status: ReturnType<typeof useStatus>;
  children: ReactNode;
}) {
  return (
    <div className="@container flex h-dvh flex-col" style={{ background: "var(--paper)" }}>
      <header
        className="flex shrink-0 items-center justify-between px-3 py-2"
        style={{ borderBottom: "1px solid var(--rule)" }}
      >
        <div className="flex items-center gap-3">
          {/* The app's own chrome, not the browser's: M7 hosts this in a
              Tauri window where there is no browser chrome to borrow. */}
          <span id="askwell-chrome-start">
            <RailDrawer />
          </span>
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
          <ProvenanceMargin />
        </aside>
      </div>

      {/* Outside the scrolling columns: the drop affordance covers the window,
          because the window is what the user is dropping onto. */}
      <DropTarget />
      <LiveLeaderCanvas />
    </div>
  );
}

/** Feeds `LeaderCanvas` the live turn's own claim-to-card pairs — split out
 * so `ShellFrame` itself does not need to know `useAsk` exists. */
function LiveLeaderCanvas() {
  const { pairs, active } = useLiveLeaderPairs();
  return <LeaderCanvas pairs={pairs} active={active} />;
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
