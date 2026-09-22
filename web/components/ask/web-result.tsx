import { retrievedDateLabel, truncatedTitle, truncatedUrl, type WebResult } from "@/lib/web-citations";

/**
 * The web results region, separate from the provenance margin.
 * `M6.5-WEB-FE-190` (`docs/ux/web-search.md` §3, `docs/ux/design-system.md`
 * §7).
 *
 * Never `ProvenanceMargin`'s `<ul>`, never `InlineSourceCards` — this is its
 * own region, meant to render *adjacent to* those, never inside either one,
 * at any width. Nothing in this file imports from `provenance-margin.tsx`
 * and nothing there imports this: the two share no implementation, per the
 * ticket's own "any reuse of the source card component — forbidden."
 *
 * Not yet called from `ask-screen.tsx` — the live turn has nowhere to carry
 * a web result yet (that wiring, and the mixed-answer case, are
 * `M6.5-WEB-FE-191`/`-192`). This is the same isolated-capability shape
 * `M6.5-WEB-BE-185`/`-188`/`-189` each shipped in.
 */
export function WebResultsRegion({ results }: { results: readonly WebResult[] }) {
  if (results.length === 0) return null;
  return (
    <section
      aria-label="Web results"
      className="flex flex-col gap-3 p-3"
      style={{
        background: "var(--surface)",
        border: "1px dashed var(--inferred)",
        borderRadius: "var(--radius)",
      }}
    >
      <p className="ask-micro" style={{ color: "var(--inferred)" }}>
        From the web &mdash; not your files
      </p>
      <ul className="flex flex-col gap-3" style={{ listStyle: "none" }}>
        {results.map((result) => (
          <li key={result.url}>
            <WebResultCard result={result} />
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * One result. Domain and title in mono (apparatus — `design-system.md` §3),
 * the passage in serif (language), both in `--inferred`/`--muted`, never
 * `--provenance` — that colour is reserved for material the user owns and
 * can open (`design-system.md` §2), which a web page never is.
 *
 * Sized to its own passage — no fixed height, no padding to match a source
 * card's shape, so a one-sentence passage renders at its natural size
 * (the ticket's own edge case).
 */
function WebResultCard({ result }: { result: WebResult }) {
  const passage = result.passage.trim();
  const title = truncatedTitle(result.title);
  const url = truncatedUrl(result.url);

  return (
    <article className="flex flex-col gap-1.5">
      <a
        href={result.url}
        target="_blank"
        rel="noopener noreferrer"
        className="ask-navigates flex flex-col gap-0.5 w-fit"
        style={{ color: "var(--ink)" }}
      >
        <span className="ask-micro" style={{ color: "var(--inferred)" }} title={result.domain}>
          {result.domain}
        </span>
        <span className="ask-micro" style={{ textTransform: "none" }} title={result.title}>
          {title}
        </span>
      </a>

      {passage !== "" ? (
        <p className="ask-prose" style={{ fontSize: "var(--t-meta)", lineHeight: "var(--t-meta-lh)" }}>
          &ldquo;{passage}&rdquo;
        </p>
      ) : null}

      <p className="ask-micro flex flex-wrap items-center gap-2" style={{ textTransform: "none" }}>
        <span style={{ color: "var(--muted)" }}>{retrievedDateLabel(result.retrievedAt)}</span>
        <a
          href={result.url}
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: "var(--muted)" }}
          title={result.url}
        >
          {url}
        </a>
      </p>
    </article>
  );
}
