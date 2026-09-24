"use client";

/**
 * Online AI in the conversation itself. `M8-ONLINE-FE-171`, `docs/ux/ask.md`
 * §5 "Online mode", `docs/states-and-edge-cases.md` §1.
 *
 * Three pieces, all inside the composer's sticky band so none of them can be
 * scrolled away from the box that sends: the marker, the switch, and the
 * disclosure that has to be answered before the first online send. The
 * wording and every decision about what to show live in
 * `lib/online-conversation.ts`. The server holds the state and enforces the
 * refusal on its own (`askwell.online`).
 *
 * The marker is `--ink` on `--surface` with a heavy left rule rather than a
 * colour of its own. `design-system.md` §2 keeps colour for how Askwell knows
 * a thing, and "online" is not a claim about knowledge. It must be
 * unmissable without being mistaken for an error, so it gets weight rather
 * than `--alarm`.
 */

import { useState } from "react";

import { useAsk } from "@/components/ask/ask-state";
import {
  confirmDisclosure,
  DISCLOSURE_CONFIRM,
  DISCLOSURE_HEADING,
  DISCLOSURE_UNDEFINED,
  markerView,
  needsDisclosure,
  SWITCH_LOCAL,
  switchLocal,
  switchOnline,
  turnBackendLabel,
} from "@/lib/online-conversation";

/** Online now, or online earlier. Never dismissible: it is a fact about the
 * conversation, not a notification. */
export function OnlineMarker() {
  const { online } = useAsk();
  const view = markerView(online);
  if (view.kind === "none") return null;
  return (
    <p
      role="status"
      className="ask-prose px-3 py-2"
      style={{
        background: "var(--surface)",
        borderLeft: `4px solid ${view.kind === "online" ? "var(--ink)" : "var(--rule-strong)"}`,
        color: view.kind === "online" ? "var(--ink)" : "var(--muted)",
        fontSize: "var(--t-ui)",
        lineHeight: "var(--t-ui-lh)",
      }}
    >
      {view.kind === "online" ? <strong>{view.text}</strong> : view.text}
    </p>
  );
}

/**
 * The per-conversation switch. There is no other place to turn online AI on
 * (`docs/ux/settings.md` §3): no global setting to forget about. Switching
 * on only authorises the destination. Nothing is sent until the disclosure
 * below is answered.
 */
export function OnlineSwitch() {
  const { online, ensureConversation, setOnline } = useAsk();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const on = online?.ai_backend === "online";

  const toggle = async (): Promise<void> => {
    setBusy(true);
    setNotice(null);
    try {
      const id = await ensureConversation();
      setOnline(on ? await switchLocal(id) : await switchOnline(id));
    } catch (error) {
      // Not configured (no provider yet), or the conversation is gone. The
      // server's own sentence says which, and that nothing left.
      setNotice(error instanceof Error ? error.message : "Online AI could not be switched.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="flex items-center gap-2">
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label="Online AI for this conversation"
        aria-describedby={notice !== null ? "online-switch-notice" : undefined}
        onClick={() => void toggle()}
        disabled={busy}
        className="ask-navigates px-3"
        style={{
          border: `1px solid ${on ? "var(--ink)" : "var(--rule-strong)"}`,
          fontSize: "var(--t-ui)",
          height: "var(--control-height)",
          fontWeight: on ? 600 : 400,
        }}
      >
        {on ? "Online AI: on" : "Local"}
      </button>
      {notice !== null ? (
        <span id="online-switch-notice" role="status" className="ask-micro" style={{ textTransform: "none" }}>
          {notice}
        </span>
      ) : null}
    </span>
  );
}

/**
 * What will leave the machine, before the first online send. While the
 * wording is undefined (issue 737) it says so, offers only the way back to local,
 * and the composer refuses to send. Once defined, it shows the server's own
 * statement and a confirmation, which the server records as a decision
 * naming this conversation.
 */
export function OnlineDisclosure() {
  const { online, conversationId, setOnline } = useAsk();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!needsDisclosure(online) || online === null || conversationId === null) return null;

  const run = async (action: () => Promise<Parameters<typeof setOnline>[0]>): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      setOnline(await action());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Askwell could not record that.");
    } finally {
      setBusy(false);
    }
  };

  const { disclosure } = online;
  return (
    <section
      aria-labelledby="online-disclosure-heading"
      className="flex flex-col gap-2 px-3 py-3"
      style={{ background: "var(--surface)", border: "1px solid var(--rule-strong)" }}
    >
      <h2
        id="online-disclosure-heading"
        style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)", fontWeight: 600 }}
      >
        {DISCLOSURE_HEADING}
      </h2>
      <p className="ask-prose">
        {disclosure.defined && disclosure.text !== null ? disclosure.text : DISCLOSURE_UNDEFINED}
      </p>
      {error !== null ? (
        <p role="alert" className="ask-prose" style={{ color: "var(--muted)" }}>
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {disclosure.defined && disclosure.version !== null ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              const version = disclosure.version;
              if (version !== null) void run(() => confirmDisclosure(conversationId, version));
            }}
            className="ask-action-primary px-4"
            style={{ fontSize: "var(--t-ui)" }}
          >
            {DISCLOSURE_CONFIRM}
          </button>
        ) : null}
        <button
          type="button"
          disabled={busy}
          onClick={() => void run(() => switchLocal(conversationId))}
          className="ask-navigates px-3"
          style={{ border: "1px solid var(--rule-strong)", fontSize: "var(--t-ui)" }}
        >
          {SWITCH_LOCAL}
        </button>
      </div>
    </section>
  );
}

/** "Answered locally" or "Answered online · model", on each finished turn
 * of a conversation that has used online AI. Nothing otherwise. */
export function TurnBackendLabel({
  turn,
}: {
  turn: Parameters<typeof turnBackendLabel>[0];
}) {
  const { online } = useAsk();
  const label = turnBackendLabel(turn, online);
  if (label === null) return null;
  return (
    <span className="ask-micro" style={{ textTransform: "none", whiteSpace: "nowrap", color: "var(--muted)" }}>
      {label}
    </span>
  );
}
