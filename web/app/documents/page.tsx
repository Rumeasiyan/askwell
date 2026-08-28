import { Suspense } from "react";

import { DocumentViewer } from "@/components/documents/document-viewer";

/**
 * The source viewer's one static route. `M1-VIEW-FE-046`.
 *
 * A single build-time page — see `document-viewer.tsx`'s own note on why the
 * document id travels as `?id=` rather than a `[id]` path segment under this
 * app's static export. `useSearchParams` requires a `Suspense` boundary even
 * for a client component that only ever renders after hydration, or the
 * static export build fails asking for one.
 */
export default function DocumentsPage() {
  return (
    <Suspense fallback={<p className="ask-micro p-4">Opening…</p>}>
      <DocumentViewer />
    </Suspense>
  );
}
