"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Rail } from "@/components/shell/rail";

/**
 * The rail, reachable when it is not a column.
 *
 * `docs/ux/design-system.md` §4: the rail is the only route to sources, memory
 * and settings, so hiding it below the breakpoint without a way back strands
 * the user. It is made reachable, not removed.
 *
 * This is a resized-window behaviour, not a mobile one. Askwell installs as a
 * desktop application and there is no phone — the target is a laptop window
 * someone has made narrow on purpose. So there is no gesture to open it, and
 * nothing here assumes touch.
 *
 * The control sits in the application's own chrome rather than the browser's,
 * because M7 hosts this in a Tauri window where there is no browser chrome to
 * borrow.
 */
export function RailDrawer() {
  const [open, setOpen] = useState(false);
  const control = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  const close = useCallback(() => {
    setOpen(false);
    // Focus returns to where it came from. Leaving it on a dismissed element
    // drops a keyboard user at the top of the document with no idea where
    // they are.
    control.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;

    // Focus moves in on open, so the first Tab is inside the drawer rather
    // than behind it.
    const first = panel.current?.querySelector<HTMLElement>("a, button");
    first?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  return (
    <>
      <button
        ref={control}
        type="button"
        // Only below the breakpoint. Above it the rail is a column and a
        // second way to reach it would be two controls for one thing.
        className="ask-navigates @3xl:hidden px-2 py-1"
        aria-expanded={open}
        aria-controls="askwell-rail-drawer"
        aria-label={open ? "Close navigation" : "Open navigation"}
        onClick={() => (open ? close() : setOpen(true))}
        style={{ border: "1px solid var(--rule)", color: "var(--muted)" }}
      >
        {/* Three rules, drawn rather than an icon font: no external asset can
            fail to load (C1), and it is six lines of markup. */}
        <span aria-hidden className="flex flex-col gap-[3px]">
          {[0, 1, 2].map((line) => (
            <span
              key={line}
              style={{ display: "block", width: 14, height: 1.5, background: "currentColor" }}
            />
          ))}
        </span>
      </button>

      {open ? (
        <>
          <div
            // Dismisses on click. Not focusable and hidden from the tree: it
            // is a way out for a pointer, and Escape is the way out for a
            // keyboard.
            aria-hidden
            onClick={close}
            className="fixed inset-0 z-40"
            style={{ background: "var(--drop)" }}
          />
          <div
            ref={panel}
            id="askwell-rail-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="fixed top-0 bottom-0 left-0 z-50 overflow-y-auto"
            style={{
              width: "var(--rail)",
              background: "var(--paper)",
              borderRight: "1px solid var(--rule-strong)",
              boxShadow: `2px 0 8px var(--drop)`,
            }}
          >
            {/* Same contents, nothing removed or reordered — a drawer that
                shows a different set of destinations is a second navigation
                to keep in step with the first. */}
            <Rail onNavigate={close} />
          </div>
        </>
      ) : null}
    </>
  );
}
