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
 *
 * `M8-ONLINE-SEC-169` gives it the first such permit: a conversation switched
 * to online AI. Its connections are listed per conversation and destination,
 * so a permitted count is attributable rather than a bare total, and a
 * conversation whose authorisation is standing right now says so.
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

          {activity.permitted_by_conversation.length > 0 ? (
            <div className="flex flex-col gap-1">
              <p className="ask-micro" style={{ textTransform: "none" }}>
                Permitted, by the conversation that made them:
              </p>
              <ul className="flex flex-col gap-1">
                {activity.permitted_by_conversation.map((item) => (
                  <li key={`${item.conversation_id}-${item.destination}`} className="ask-micro" style={{ textTransform: "none" }}>
                    Conversation {item.conversation_id.slice(0, 8)} → {item.destination}: {item.permitted}
                    {activity.authorised.some((open) => open.conversation_id === item.conversation_id)
                      ? " · online now"
                      : ""}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

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
