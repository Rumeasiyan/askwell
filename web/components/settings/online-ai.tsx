/**
 * The online AI section — `docs/ux/settings.md` §3, `M7-SET-FE-150`.
 *
 * Online AI is switched on per conversation, from the conversation
 * (`M8-ONLINE-FE-171`), so there is deliberately no switch here: one would
 * read as the global setting that must not exist. The one thing this section
 * collects is the provider key (`M8-KEY-FE-174`, `online-key.tsx`), and what
 * it is for, when it is used and who pays is stated above the field, so it is
 * read before anything is pasted. The wording lives in `lib/online-ai.ts`
 * and `lib/online-key.ts`.
 */

import { OnlineKey } from "@/components/settings/online-key";
import {
  ONLINE_AI_PAYLOAD,
  ONLINE_AI_PER_CONVERSATION,
  ONLINE_AI_WHAT,
  ONLINE_AI_WHERE,
} from "@/lib/online-ai";
import { KEY_COST, KEY_PROVIDERS, KEY_PURPOSE, KEY_STORAGE } from "@/lib/online-key";

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

      <div className="flex flex-col gap-2">
        <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>Your key</h3>
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          {KEY_PURPOSE}
        </p>
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          {KEY_PROVIDERS}
        </p>
        <OnlineKey />
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          {KEY_STORAGE}
        </p>
      </div>

      <div className="flex flex-col gap-2" style={{ color: "var(--muted)" }}>
        <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>What it costs</h3>
        <p className="ask-prose">{KEY_COST}</p>
      </div>

      <div className="flex flex-col gap-2" style={{ color: "var(--muted)" }}>
        <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>What leaves this machine</h3>
        <p className="ask-prose">{ONLINE_AI_PAYLOAD}</p>
      </div>
    </section>
  );
}
