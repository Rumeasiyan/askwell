"use client";

/**
 * Privacy and security. `M7-SET-FE-147`, `docs/ux/settings.md` §4.
 *
 * Three displays, none sharing a fetch with another so one failing does not
 * blank the rest — same shape `storage.tsx` already established for its own
 * section:
 *
 * 1. The passphrase control (`passphrase.tsx`), surfacing `M7-SEC-BE-151`.
 * 2. Network activity, stated as a fact with the proxy's live count
 *    (`network-activity.tsx`) — never a toggle, and no control on this
 *    screen pre-authorises egress of any kind (this ticket's own Validation
 *    Rule).
 * 3. Connected databases (`connections.tsx`, `M4-CONN-FE-096`), kept as its
 *    own component rather than folded in here — its count is a real, local
 *    fact about what the user connected and must stay visibly separate from
 *    the network-activity figure above, never confusable with it.
 *
 * **There is no web-search setting here, and there must never be one**
 * (`../ux/web-search.md` §1, §5). When M6.5 lands, escalation history has a
 * place to land in the network-activity display above — named per
 * destination, as `network-activity.tsx` already documents — not a fourth
 * subsection and not a switch.
 */

import { Connections } from "@/components/settings/connections";
import { NetworkActivityStatement } from "@/components/settings/network-activity";
import { PassphraseControl } from "@/components/settings/passphrase";

export function PrivacySecurity() {
  return (
    <section className="flex flex-col gap-6">
      <h2 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>
        Privacy and security
      </h2>

      <PassphraseControl />
      <NetworkActivityStatement />
      <Connections />
    </section>
  );
}
