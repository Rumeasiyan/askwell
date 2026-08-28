/**
 * Search across sources, independent of the assistant. `M2-FAIL-FE-060`.
 *
 * `askwell.retrieve.search` (server) is the retrieval — dense and lexical,
 * fused, reranked if the assistant can — this is the fetch and the shape the
 * degraded-assistant surface on Ask renders. `keywordOnly` is the one fact
 * that surface cannot guess on its own: dense search needs the model to
 * embed the query, so it is the server, not the browser, that knows whether
 * a result list is a real hybrid search or keyword matches alone.
 */

export interface SearchHit {
  chunkId: string;
  documentId: string;
  filename: string;
  anchorKind: string | null;
  heading: string | null;
  pageFrom: number | null;
  pageTo: number | null;
  passage: string;
}

export interface SearchResponse {
  keywordOnly: boolean;
  results: SearchHit[];
}

interface RawSearchHit {
  chunk_id: string;
  document_id: string;
  filename: string;
  anchor_kind: string | null;
  heading: string | null;
  page_from: number | null;
  page_to: number | null;
  passage: string;
}

/** Pure, so the snake_case-to-camelCase mapping is checkable without a
 * fetch mock — the same reason `applyCitation` (`lib/citations.ts`) is a
 * pure fold rather than buried inside the function that calls it. */
export function parseSearchResponse(body: {
  keyword_only: boolean;
  results: RawSearchHit[];
}): SearchResponse {
  return {
    keywordOnly: body.keyword_only,
    results: body.results.map((hit) => ({
      chunkId: hit.chunk_id,
      documentId: hit.document_id,
      filename: hit.filename,
      anchorKind: hit.anchor_kind,
      heading: hit.heading,
      pageFrom: hit.page_from,
      pageTo: hit.page_to,
      passage: hit.passage,
    })),
  };
}

export async function fetchSearch(
  query: string,
  sourceId?: string | null,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query });
  if (sourceId) params.set("source_id", sourceId);
  const response = await fetch(`/search?${params.toString()}`, {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} when searching.`);
  }
  const body = (await response.json()) as { keyword_only: boolean; results: RawSearchHit[] };
  return parseSearchResponse(body);
}
