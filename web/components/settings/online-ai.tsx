"use client";

/**
 * The online AI section — `docs/ux/settings.md` §3, `M7-SET-FE-150`.
 *
 * Visible and inert until M8. The switch is focusable and clickable on
 * purpose — `aria-disabled`, not `disabled` — so that someone who tries to
 * turn it on is told plainly why it will not move, instead of pressing a
 * control that silently ignores them. It never reaches "on", and nothing in
 * this section fetches or collects anything: no input, no form, no request.
 * The wording lives in `lib/online-ai.ts`.
 */

import { useState } from "react";

import {
  attemptToEnable,
  ONLINE_AI_INITIAL,
  ONLINE_AI_KEY,
  ONLINE_AI_PAYLOAD,
  ONLINE_AI_PER_CONVERSATION,
  ONLINE_AI_STATUS,
  ONLINE_AI_WHAT,
  type OnlineAiView,
} from "@/lib/online-ai";

export function OnlineAi() {
  const [view, setView] = useState<OnlineAiView>(ONLINE_AI_INITIAL);

  return (
    <section className="flex flex-col gap-6" aria-labelledby="online-ai-heading">
      <h2 id="online-ai-heading" style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>
        Online AI
      </h2>

      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-3">
          <button
            type="button"
            role="switch"
            aria-checked={view.on}
            aria-disabled="true"
            aria-describedby="online-ai-status"
            onClick={() => setView(attemptToEnable())}
            className="px-2 py-1"
            style={{ border: "1px solid var(--rule)", color: "var(--muted)", cursor: "not-allowed" }}
          >
            Use online AI
          </button>
          <span id="online-ai-status" className="ask-micro" style={{ color: "var(--muted)", textTransform: "none" }}>
            {ONLINE_AI_STATUS}
          </span>
        </div>
        {view.notice !== null ? (
          <p role="status" className="ask-prose">
            {view.notice}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-2" style={{ color: "var(--muted)" }}>
        <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>What it will be</h3>
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
