/**
 * The rail drawer's two decisions that are worth pinning in a test
 * (`M7-FIX-FE-173`), kept free of the DOM so they run under `node --test`.
 */

/**
 * Where `Tab` goes inside a modal drawer. `null` means "let the browser do it"
 * — the move stays inside anyway, so there is nothing to correct.
 *
 * Only the two edges wrap: `Tab` off the last control lands on the first, and
 * `Shift+Tab` off the first lands on the last. Focus that is somehow outside
 * the drawer (`current === -1`) is pulled back in at the end the key points
 * towards, rather than being allowed to wander into the screen the drawer is
 * covering.
 */
export function trapTab(count: number, current: number, backwards: boolean): number | null {
  if (count === 0) return null;
  if (current === -1) return backwards ? count - 1 : 0;
  if (backwards && current === 0) return count - 1;
  if (!backwards && current === count - 1) return 0;
  return null;
}

/**
 * Whether the drawer's own control is still showing. The control is hidden by
 * the same container query that shows the rail as a column (`@3xl:hidden` in
 * `rail-drawer.tsx`), so "the control has no box" *is* "the window has been
 * widened past the breakpoint" — measured by the container the shell chose,
 * not by the viewport (issue 657).
 */
export function controlShowing(box: { width: number; height: number } | undefined): boolean {
  return box !== undefined && (box.width > 0 || box.height > 0);
}
