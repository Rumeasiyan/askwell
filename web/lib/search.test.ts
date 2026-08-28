/**
 * `parseSearchResponse`'s field mapping — the part of `lib/search.ts` worth
 * checking without a fetch mock (`M2-FAIL-FE-060`).
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { parseSearchResponse } from "./search.ts";

test("parseSearchResponse maps snake_case fields to camelCase", () => {
  const parsed = parseSearchResponse({
    keyword_only: true,
    results: [
      {
        chunk_id: "c1",
        document_id: "d1",
        filename: "contract.pdf",
        anchor_kind: null,
        heading: "Termination",
        page_from: 4,
        page_to: 4,
        passage: "Either party may terminate on ninety days notice.",
      },
    ],
  });

  assert.equal(parsed.keywordOnly, true);
  assert.deepEqual(parsed.results, [
    {
      chunkId: "c1",
      documentId: "d1",
      filename: "contract.pdf",
      anchorKind: null,
      heading: "Termination",
      pageFrom: 4,
      pageTo: 4,
      passage: "Either party may terminate on ninety days notice.",
    },
  ]);
});

test("parseSearchResponse returns an empty list rather than throwing on no hits", () => {
  const parsed = parseSearchResponse({ keyword_only: false, results: [] });
  assert.equal(parsed.keywordOnly, false);
  assert.deepEqual(parsed.results, []);
});
