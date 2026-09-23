/**
 * About — `docs/ux/settings.md` §7, `M7-DOC-DOC-163`.
 *
 * Deliberately narrow: version, licence, a link to the source and a link to
 * the notices file this ticket exists to produce (`web/public/notices.md`,
 * copied from the repository's own `NOTICES.md` at build time — see
 * `scripts/copy-notices.mjs`). Update checking (`docs/ux/settings.md` §7's
 * opt-in weekly check, `M7-UPDATE-BE-161`'s backend) is a real, separate
 * surface this section does not build — no ticket has built its frontend
 * yet, and inventing one here would be scope this ticket's own granularity
 * note ("one file plus one check") does not ask for. Filed as a gap rather
 * than silently left for the next reader to notice.
 *
 * The repository the source link points at is private today
 * (`AGENTS.md` §8 — tracker `Rumeasiyan/askwell`, private); the link is
 * written once, here, rather than guessed at per-caller, so opening it is
 * the one place that changes when the repository's visibility does.
 */

import { VERSION } from "@/lib/version";

const REPO_URL = "https://github.com/Rumeasiyan/askwell";

export function About() {
  return (
    <section className="flex flex-col gap-3">
      <h2 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>About</h2>
      <dl className="ask-prose flex flex-col gap-2">
        <div className="flex items-baseline gap-2">
          <dt style={{ color: "var(--muted)" }}>Version</dt>
          <dd>{VERSION}</dd>
        </div>
        <div className="flex items-baseline gap-2">
          <dt style={{ color: "var(--muted)" }}>Licence</dt>
          <dd>Apache-2.0</dd>
        </div>
        <div className="flex items-baseline gap-2">
          <dt style={{ color: "var(--muted)" }}>Source</dt>
          <dd>
            <a href={REPO_URL} target="_blank" rel="noreferrer">
              {REPO_URL}
            </a>
          </dd>
        </div>
        <div className="flex items-baseline gap-2">
          <dt style={{ color: "var(--muted)" }}>Report a problem</dt>
          <dd>
            <a href={`${REPO_URL}/issues/new`} target="_blank" rel="noreferrer">
              Open an issue
            </a>
          </dd>
        </div>
        <div className="flex items-baseline gap-2">
          <dt style={{ color: "var(--muted)" }}>Notices</dt>
          <dd>
            <a href="/notices.md" target="_blank" rel="noreferrer">
              Third-party notices and licences
            </a>
          </dd>
        </div>
      </dl>
    </section>
  );
}
