import { Folders } from "@/components/settings/folders";
import { HardwareProfile } from "@/components/settings/hardware-profile";
import { PrivacySecurity } from "@/components/settings/privacy-security";
import { RetrievalThresholdControl } from "@/components/settings/retrieval-threshold";
import { Storage } from "@/components/settings/storage";

/**
 * Settings — five real sections so far.
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
 * this section exists to draw. The rest of the screen is still its empty
 * state, because `docs/states-and-edge-cases.md` requires every surface to
 * have one and a route stub with nothing in it teaches the next person that
 * empty states are optional.
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

      <section className="flex flex-col gap-3">
        <h2 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>
          Hardware profile
        </h2>
        <HardwareProfile />
      </section>

      <Folders />

      <section className="flex flex-col gap-3">
        <h2 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>
          Retrieval threshold
        </h2>
        <RetrievalThresholdControl />
      </section>

      <Storage />

      <PrivacySecurity />
    </div>
  );
}
