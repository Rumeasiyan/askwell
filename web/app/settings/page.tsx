import { About } from "@/components/settings/about";
import { Folders } from "@/components/settings/folders";
import { ModelAndSpeed } from "@/components/settings/model-and-speed";
import { OnlineAi } from "@/components/settings/online-ai";
import { PrivacySecurity } from "@/components/settings/privacy-security";
import { Storage } from "@/components/settings/storage";
import { YourData } from "@/components/settings/your-data";

/**
 * Settings — eight real sections so far.
 *
 * The folders Askwell may read arrive here in M1 because that is where the
 * cold-start walkthrough looks for them: nominate a folder while adding a
 * source, then open settings and see it listed. Connected databases arrives
 * the same way in `M4-CONN-FE-096`. The retrieval threshold arrives with
 * `M5-TRACE-FE-122` — one setting brought forward ahead of the general M7
 * settings surface, the same way the two before it were, because
 * `docs/ux/settings.md` §2 requires it reachable here with the same warning
 * the abstention trace's own near-miss control uses
 * (`web/components/settings/retrieval-threshold.tsx`, shared by both). The
 * hardware profile override arrives with `M7-PROBE-FE-138` — the welcome
 * screen's warn-and-continue's other half, so a profile chosen (or fallen
 * back to) at install can be changed afterwards. Storage arrives with
 * `M7-SET-FE-148` (`web/components/settings/storage.tsx`) — per-source
 * index size, the log budget and its current use, the retention window, and
 * the at-the-limit statement; export and prune is a stated, disabled entry
 * point because its backend (`M7-LOG-BE-155`) does not exist yet. Privacy
 * and security arrives with `M7-SET-FE-147`
 * (`web/components/settings/privacy-security.tsx`) — the passphrase control
 * surfacing `M7-SEC-BE-151`, the egress proxy's own live network-activity
 * count (never a toggle), and connected databases, which moves here from
 * its previous standalone placement because its read-only status is exactly
 * the "permitted destination, shown separately from the local-mode zero"
 * this section exists to draw. Your data began with `M7-LOG-FE-156`'s
 * verify the log and is completed by `M7-DATA-FE-160`
 * (`web/components/settings/your-data.tsx`) — all six of
 * `docs/ux/settings.md` §6's actions, with deleting a single source linked
 * to the Library rather than rebuilt here. About arrives with `M7-DOC-DOC-163`
 * (`web/components/settings/about.tsx`) — version, licence, a link to the
 * source and a link to `NOTICES.md`, copied into `public/` at build time
 * (`web/scripts/copy-notices.mjs`) rather than duplicated, and
 * `M7-DOC-DOC-164` adds the support boundary and the security route, copied
 * the same way (`web/scripts/copy-support.mjs`). `M7-SET-FE-149` completes
 * it: every bundled text shown in the page in full, addresses as copyable
 * text, and `docs/ux/settings.md` §7's update-check opt-in, off unless the
 * person turned it on. Model and speed
 * arrives with `M7-SET-FE-146` (`web/components/settings/model-and-speed.tsx`)
 * as the first section, per `docs/ux/settings.md` §1's order — it gathers the
 * hardware profile and retrieval threshold above under one heading, beside
 * the model in use, its measured memory and throughput, and the swap. Online
 * AI arrives with `M7-SET-FE-150` (`web/components/settings/online-ai.tsx`)
 * second, per the same order, describing the person's-own-key model
 * `docs/decisions.md` 2026-09-23 settled on; `M8-KEY-FE-174` adds the key
 * itself (`web/components/settings/online-key.tsx`). The rest of the
 * screen is still its empty state, because `docs/states-and-edge-cases.md`
 * requires every surface to have one and a route stub with nothing in it
 * teaches the next person that empty states are optional.
 */
export default function SettingsPage() {
  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-3">
        <h1 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>Settings</h1>
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          Deployment profile, retention, and what Askwell has been refused from doing.
        </p>
        <p
          className="ask-prose px-4 py-3"
          style={{
            background: "var(--surface)",
            borderRadius: "var(--radius)",
            border: "1px solid var(--rule)",
          }}
        >
          The rest of the settings that exist today are environment variables. The surface for
          them arrives in M7.
        </p>
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          Voice&apos;s past-latency indicator waits 3.5 seconds on an <code>accelerated</code>{" "}
          hardware profile and 8 seconds on every other profile, including one that could not be
          determined.
        </p>
      </section>

      <ModelAndSpeed />

      <OnlineAi />

      <Folders />

      <Storage />

      <PrivacySecurity />

      <YourData />

      <About />
    </div>
  );
}
