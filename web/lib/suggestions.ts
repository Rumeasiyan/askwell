/**
 * Corpus-derived suggested questions for the Ask screen's empty state.
 * `docs/ux/ask.md` §5, `M1-LIB-FE-051`.
 *
 * `askwell.suggestions.suggested_questions` (server) is where the heuristic
 * lives — real filenames, real headings, real terms, no model call. This is
 * just the fetch.
 */

export interface Suggestion {
  question: string;
  filename: string;
}

export async function fetchSuggestions(signal?: AbortSignal): Promise<Suggestion[]> {
  const response = await fetch("/suggestions", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} when asked for suggestions.`);
  }
  const body = (await response.json()) as { suggestions: Suggestion[] };
  return body.suggestions;
}
