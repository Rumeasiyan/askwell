/**
 * The online AI section — `docs/ux/settings.md` §3, `M7-SET-FE-150`.
 *
 * Words only. Online AI is switched on per conversation, from the
 * conversation (`M8-ONLINE-FE-171`), so there is deliberately no switch here:
 * one would read as the global setting that must not exist. Nothing in this
 * section fetches or collects anything. The wording lives in
 * `lib/online-ai.ts`.
 */

import {
  ONLINE_AI_KEY,
  ONLINE_AI_PAYLOAD,
  ONLINE_AI_PER_CONVERSATION,
  ONLINE_AI_WHAT,
  ONLINE_AI_WHERE,
} from "@/lib/online-ai";

export function OnlineAi() {
  return (
    <section className="flex flex-col gap-6" aria-labelledby="online-ai-heading">
      <h2 id="online-ai-heading" style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>
        Online AI
      </h2>

      <p className="ask-prose">{ONLINE_AI_WHERE}</p>

      <div className="flex flex-col gap-2" style={{ color: "var(--muted)" }}>
        <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>What it is</h3>
        <p className="ask-prose">{ONLINE_AI_WHAT}</p>
        <p className="ask-prose">{ONLINE_AI_PER_CONVERSATION}</p>
      </div>

      <div className="flex flex-col gap-2" style={{ color: "var(--muted)" }}>
        <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>Your key, your bill</h3>
        <p className="ask-prose">{ONLINE_AI_KEY}</p>
      </div>

      <div className="flex flex-col gap-2" style={{ color: "var(--muted)" }}>
        <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>What leaves this machine</h3>
        <p className="ask-prose">{ONLINE_AI_PAYLOAD}</p>
      </div>
    </section>
  );
}
