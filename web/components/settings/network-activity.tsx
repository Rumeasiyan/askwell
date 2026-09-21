"use client";

/**
 * Network activity: a statement, not a toggle. `M7-SET-FE-147`,
 * `docs/ux/settings.md` §4.
 *
 * The count is `GET /network`'s own figure — `lib/network.ts` never
 * substitutes zero for an unreadable proxy, and neither does this
 * component: `available === false` renders "unavailable", full stop, per
 * this ticket's own Edge Case. A non-zero refusal count is shown plainly,
 * with its destinations, because hiding it would be the opposite of the
 * point the count exists to prove.
 *
 * "Permitted" here is the proxy's own count of anything it let through — a
 * user's own database reaches its destination over the internal Compose
 * network the proxy does not sit on (`connections.py`), so today this stays
 * at the same measured zero as refused. It is rendered as its own line
 * rather than folded into refused so a future permit (a live connection's
 * own destination, online AI, a web search) has somewhere to land without
 * reshaping this component — named per destination, never one incremented
 * total, matching this ticket's own Assumption.
 */

import { useEffect, useState } from "react";

import { fetchNetworkActivity, type NetworkActivity } from "@/lib/network";

export function NetworkActivityStatement() {
  const [activity, setActivity] = useState<NetworkActivity | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchNetworkActivity(controller.signal)
      .then(setActivity)
      .catch((thrown: unknown) => {
        if (!controller.signal.aborted) {
          setFailure(thrown instanceof Error ? thrown.message : "Askwell could not read network activity.");
        }
      });
    return () => controller.abort();
  }, []);

  return (
    <div className="flex flex-col gap-2">
      <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>Network activity</h3>

      {failure !== null || activity?.available === false ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          Unavailable — the egress proxy&apos;s counters could not be read.
          {activity?.unavailable_reason ? ` ${activity.unavailable_reason}` : ""} This is not the
          same as zero; it means the figure is unknown right now.
        </p>
      ) : activity === null ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          Reading…
        </p>
      ) : (
        <>
          <p className="ask-prose" style={{ margin: 0 }}>
            <strong>{activity.permitted}</strong> outbound request{activity.permitted === 1 ? "" : "s"}{" "}
            permitted · <strong>{activity.refused}</strong> refused, measured by the egress proxy
            itself. Not a setting — this is what actually happened.
          </p>

          {activity.refused !== null && activity.refused > 0 ? (
            <div className="flex flex-col gap-1">
              <p className="ask-micro" style={{ textTransform: "none" }}>
                Most recent refusals (of {activity.recent_capped_at} kept):
              </p>
              <ul className="flex flex-col gap-1">
                {activity.recent.map((refusal, index) => (
                  <li key={`${refusal.service}-${refusal.destination}-${index}`} className="ask-micro" style={{ textTransform: "none" }}>
                    {refusal.service} → {refusal.destination}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
