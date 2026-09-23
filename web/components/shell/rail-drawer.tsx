"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Rail } from "@/components/shell/rail";
import { controlShowing, trapTab } from "@/lib/drawer";

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
 *
 * `M7-FIX-FE-173`: open, the panel covers that control — it sits in the same
 * top-left corner — so the panel carries its own close control in the same
 * place. Without it the only way out was a scrim nobody is told about, which
 * is how a 390px window came to look like a rail stuck over the content.
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

    // Focus moves in on open, onto where you are, so the first Tab is inside
    // the drawer rather than behind it.
    const here =
      panel.current?.querySelector<HTMLElement>('a[aria-current="page"]') ??
      panel.current?.querySelector<HTMLElement>("a");
    here?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
      if (event.key !== "Tab" || !panel.current) return;
      // `aria-modal` tells assistive technology the rest is inert; it does
      // not stop Tab walking into the screen underneath. This does.
      const stops = [...panel.current.querySelectorAll<HTMLElement>("a[href], button")];
      const current = stops.indexOf(document.activeElement as HTMLElement);
      const next = trapTab(stops.length, current, event.shiftKey);
      if (next === null) return;
      event.preventDefault();
      stops[next]?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  useEffect(() => {
    if (!open || !control.current) return;
    // Widened past the breakpoint while open: the rail is a column again, so
    // the drawer resolves rather than staying a stuck overlay. The trigger is
    // the control itself losing its box to `@3xl:hidden` — the shell's own
    // container query, not `matchMedia` on the viewport, which is not what
    // changes in a Tauri window (issue 657). The panel and scrim are hidden by
    // the same query too, so there is no frame where they overlay the column.
    const observer = new ResizeObserver(([entry]) => {
      if (!controlShowing(entry?.contentRect)) setOpen(false);
    });
    observer.observe(control.current);
    return () => observer.disconnect();
  }, [open]);

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
            className="fixed inset-0 z-40 @3xl:hidden"
            style={{ background: "var(--drop)" }}
          />
          <div
            ref={panel}
            id="askwell-rail-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="fixed top-0 bottom-0 left-0 z-50 overflow-y-auto @3xl:hidden"
            style={{
              width: "var(--rail)",
              background: "var(--paper)",
              borderRight: "1px solid var(--rule-strong)",
              boxShadow: `2px 0 8px var(--drop)`,
            }}
          >
            {/* The chrome bar's own inset, so the close control sits in the
                corner the open control was in. */}
            <div className="flex items-center px-3 py-2">
              <button
                type="button"
                className="ask-navigates px-2 py-1"
                aria-label="Close navigation"
                onClick={close}
                style={{ border: "1px solid var(--rule)", color: "var(--muted)" }}
              >
                {/* Two of the menu control's rules, crossed. */}
                <span aria-hidden className="relative block" style={{ width: 14, height: 10.5 }}>
                  {[45, -45].map((angle) => (
                    <span
                      key={angle}
                      style={{
                        position: "absolute",
                        top: 4.5,
                        left: 0,
                        width: 14,
                        height: 1.5,
                        background: "currentColor",
                        transform: `rotate(${angle}deg)`,
                      }}
                    />
                  ))}
                </span>
              </button>
            </div>
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
