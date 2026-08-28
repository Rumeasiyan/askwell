import { AskScreen } from "@/components/ask/ask-screen";

/**
 * Route: `/`. `docs/ux/ask.md`.
 *
 * No `Suspense` boundary needed here: `AskScreen` reads `?turn=`/`?claim=`
 * (`useSearchParams`, `M1-VIEW-FE-048`'s "back to answer") from a small
 * isolated subcomponent that carries its own boundary, precisely so this
 * page keeps rendering in full statically — the version line
 * (`scripts/check-version.mjs`'s own check) and every corpus state would
 * otherwise render as a Suspense fallback in the exported `index.html`
 * instead of the real content, same as `documents/page.tsx` accepts for a
 * screen that has nothing to show *without* its query string.
 */
export default function AskPage() {
  return <AskScreen />;
}
