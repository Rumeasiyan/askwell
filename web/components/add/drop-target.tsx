"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { carriesFiles, fromDrop } from "@/lib/selection";
import { useAdd } from "./add-state";

/**
 * Drag-and-drop, anywhere in the application.
 *
 * `docs/ux/add-source.md` §1: the primary path, and not confined to the
 * add-source screen. The scenario the ticket names is someone dropping a
 * folder of contracts onto the **Ask** screen — the flow has to take over from
 * wherever they are, because "go to the right screen first" is exactly the
 * wizard step this product is trying not to have.
 *
 * Listeners are on `window` rather than on a wrapper element for a reason that
 * is not stylistic: without a `dragover` handler that calls `preventDefault`,
 * dropping a PDF anywhere the app does not cover makes the *browser* open it,
 * navigating away from Askwell and losing the drop entirely.
 */
export function DropTarget() {
  const { accept } = useAdd();
  const router = useRouter();
  const [over, setOver] = useState(false);

  // dragenter and dragleave fire for every element crossed, so the leave that
  // matters is only the one that balances the first enter. A boolean alone
  // makes the affordance flicker on every hairline it passes over.
  const depth = useRef(0);

  useEffect(() => {
    const enter = (event: DragEvent): void => {
      if (!carriesFiles(event.dataTransfer)) return;
      event.preventDefault();
      depth.current += 1;
      setOver(true);
    };

    const move = (event: DragEvent): void => {
      if (!carriesFiles(event.dataTransfer)) return;
      event.preventDefault();
      // The browser's cursor vocabulary has no word for "index in place", and
      // "copy" is the one every platform renders. Nothing is copied.
      if (event.dataTransfer !== null) event.dataTransfer.dropEffect = "copy";
    };

    const leave = (event: DragEvent): void => {
      if (!carriesFiles(event.dataTransfer)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setOver(false);
    };

    const drop = (event: DragEvent): void => {
      if (!carriesFiles(event.dataTransfer)) return;
      event.preventDefault();
      depth.current = 0;
      setOver(false);
      const transfer = event.dataTransfer;
      if (transfer === null) return;
      // Started here and awaited inside: the item list is emptied the moment
      // this handler returns, so the walk has to begin before it does.
      void fromDrop(transfer).then(accept);
      router.push("/sources/add/");
    };

    window.addEventListener("dragenter", enter);
    window.addEventListener("dragover", move);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragover", move);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, [accept, router]);

  if (!over) return null;

  return (
    <div
      // Inert: it is an affordance, not a target. The window is the target, so
      // an overlay that swallowed the drop would be the one thing that breaks
      // it — and the outline has to be visible over whatever screen is behind.
      aria-hidden
      className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center p-8"
      style={{ background: "var(--drop)" }}
    >
      <div
        className="flex flex-col items-center gap-2 px-8 py-6"
        style={{
          background: "var(--surface)",
          border: "2px dashed var(--provenance)",
          borderRadius: "var(--radius)",
          boxShadow: "0 4px 16px var(--drop)",
        }}
      >
        <p style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>
          Drop to add
        </p>
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          Files or whole folders. Askwell reads them where they are and copies nothing.
        </p>
      </div>
    </div>
  );
}
