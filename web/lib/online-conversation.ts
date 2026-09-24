/**
 * Online AI, one conversation at a time. `M8-ONLINE-FE-171`,
 * `docs/ux/ask.md` §5 "Online mode", `docs/states-and-edge-cases.md` §1.
 *
 * The server decides everything that matters here (`askwell.online`): whether
 * the conversation is online, whether it ever was, whether a statement of
 * what it sends exists, and whether this conversation confirmed it. It also
 * refuses a question on its own when the confirmation is missing, so the
 * composer's gate below is how the refusal is explained, not the only thing
 * standing between a question and the provider.
 *
 * There is no global setting and nothing here is stored in the browser. A
 * conversation is local unless it was switched online, and a new one always
 * starts local.
 */

export interface OnlineDisclosure {
  /** `false` until the wording of what is sent is decided (issue 737). While it
   * is `false`, nothing can be confirmed and nothing is sent. */
  defined: boolean;
  version: string | null;
  text: string | null;
  confirmed: boolean;
}

/** `GET/POST/DELETE /conversations/{id}/online`, `askwell.online.OnlineState.as_dict`. */
export interface OnlineConversationState {
  conversation_id: string;
  ai_backend: "local" | "online";
  destination: string | null;
  expires_in_seconds: number | null;
  available: boolean;
  unavailable_reason: string | null;
  used_online: boolean;
  /** Why its most recent authorisation ended, from its revocation record
   * (`askwell.online`). `null` while online and for one never switched on.
   * `M8-KEY-FE-175`. */
  ended_reason: string | null;
  disclosure: OnlineDisclosure;
  send_permitted: boolean;
}

async function readState(response: Response): Promise<OnlineConversationState> {
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error ?? `Askwell answered ${response.status} about online AI.`);
  }
  return (await response.json()) as OnlineConversationState;
}

/** An empty, local conversation, so it can be switched online before its
 * first question. The disclosure has to come before the first send. */
export async function createConversation(): Promise<string> {
  const response = await fetch("/conversations", { method: "POST" });
  if (!response.ok) throw new Error(`Askwell answered ${response.status} to a new conversation.`);
  const body = (await response.json()) as { conversation_id: string };
  return body.conversation_id;
}

export async function fetchOnlineState(
  conversationId: string,
  signal?: AbortSignal,
): Promise<OnlineConversationState> {
  return readState(
    await fetch(`/conversations/${conversationId}/online`, {
      headers: { accept: "application/json" },
      ...(signal ? { signal } : {}),
    }),
  );
}

export async function switchOnline(conversationId: string): Promise<OnlineConversationState> {
  return readState(await fetch(`/conversations/${conversationId}/online`, { method: "POST" }));
}

export async function switchLocal(conversationId: string): Promise<OnlineConversationState> {
  return readState(await fetch(`/conversations/${conversationId}/online`, { method: "DELETE" }));
}

/** The confirmation, a decisions record naming the conversation. Names the
 * version the user was shown, so words that changed underneath them are
 * refused rather than confirmed. */
export async function confirmDisclosure(
  conversationId: string,
  version: string,
): Promise<OnlineConversationState> {
  return readState(
    await fetch(`/conversations/${conversationId}/online/disclosure`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ version }),
    }),
  );
}

// --- what the screen says ------------------------------------------------------

export const DISCLOSURE_HEADING = "Before anything is sent: what will leave this machine";

/** Shown in place of the statement while issue 737 is open. It says the payload
 * is not defined and that nothing will be sent, rather than guessing. */
export const DISCLOSURE_UNDEFINED =
  "Askwell has not yet defined exactly what online AI would send, so it will not send " +
  "anything. Questions in this conversation are refused until that is defined. Switch " +
  "back to local to keep asking. Nothing has left this machine.";

export const DISCLOSURE_CONFIRM = "I understand. Send my questions online";

export const SWITCH_LOCAL = "Switch back to local";

/** Beside the Ask button while a send is refused. */
export const SEND_REFUSED =
  "Not sent. Online AI is on for this conversation, and what it sends has not been confirmed.";

export type MarkerView =
  | { kind: "none" }
  | { kind: "online"; text: string }
  | { kind: "was_online"; text: string };

function until(expiresInSeconds: number | null, now: number): string {
  if (expiresInSeconds === null) return "";
  const at = new Date(now + expiresInSeconds * 1000);
  return ` until ${at.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
}

/**
 * The persistent marker. Online now, online earlier (lapsed, switched back,
 * or ended by a restart), or nothing at all for a conversation that was
 * never switched on. The second case is what someone resuming an old
 * conversation sees, and it is why the marker reads the record rather than
 * only the live state.
 */
export function markerView(
  state: OnlineConversationState | null,
  now: number = Date.now(),
): MarkerView {
  if (state === null) return { kind: "none" };
  if (state.ai_backend === "online") {
    const where = state.destination !== null ? ` Questions go to ${state.destination}.` : "";
    return {
      kind: "online",
      text: `Online AI is on for this conversation${until(state.expires_in_seconds, now)}.${where}`,
    };
  }
  if (state.used_online) {
    const ended = state.ended_reason !== null ? ENDED_BECAUSE[state.ended_reason] : undefined;
    const earlier = ended !== undefined ? `earlier, until ${ended.because}` : "earlier";
    return {
      kind: "was_online",
      text:
        `Online AI was on in this conversation ${earlier}. It is local now: nothing you ask ` +
        `here leaves this machine.${ended?.next !== undefined ? ` ${ended.next}` : ""}`,
    };
  }
  return { kind: "none" };
}

/**
 * Why online AI ended, where the reason tells the user something to do or
 * something they did not see happen. `M8-KEY-FE-175`. A refusal names the
 * provider, never Askwell, because the fix is with the provider, and the two
 * refusals have different fixes. Coming back online is always the user's
 * choice, so the next step says "switch it back on", never that it will
 * return. Ending by the switch, the time limit or a restart keeps the plain
 * marker: the first the user did, and the others are reconciled into one
 * record that cannot say which it was.
 */
const ENDED_BECAUSE: Record<string, { because: string; next?: string }> = {
  provider_quota_exhausted: {
    because: "your provider account ran out of quota",
    next: "Add more with your provider, then switch online AI back on if you want it.",
  },
  provider_rejected_key: {
    because: "your provider rejected your key",
    next: "Check the key with your provider or replace it in Settings, then switch online AI back on if you want it.",
  },
  key_removed: { because: "you removed your provider key" },
  key_replaced: { because: "you replaced your provider key with one for a different provider" },
};

/** The line under the version at the top of the Ask screen. It must not say
 * "nothing leaves this machine" while that is not true. */
export function machineLine(state: OnlineConversationState | null): string {
  return state?.ai_backend === "online"
    ? "online AI is on for this conversation"
    : "nothing leaves this machine";
}

/** Whether the disclosure has to be shown and answered before the next send. */
export function needsDisclosure(state: OnlineConversationState | null): boolean {
  return state !== null && state.ai_backend === "online" && !state.send_permitted;
}

/** Whether the composer may send. A local conversation always may. An
 * online one may only once what it sends is defined and confirmed. */
export function sendAllowed(state: OnlineConversationState | null): boolean {
  return !needsDisclosure(state);
}

/**
 * Which backend answered a finished turn, for a conversation that has used
 * online AI (issue 734). `null` means show nothing: a conversation that was never
 * online, or a turn that has not answered. Earlier local turns in a conversation
 * switched online midway read "Answered locally".
 */
export function turnBackendLabel(
  turn: { status: string; modelIdentity: { source: string; display_name: string | null } | null },
  state: OnlineConversationState | null,
): string | null {
  if (state === null || (state.ai_backend !== "online" && !state.used_online)) return null;
  // Only a turn that produced an answer has a backend to name. A failed or
  // refused one did not answer at all.
  if (turn.status !== "completed" && turn.status !== "stopped") return null;
  if (turn.modelIdentity?.source === "online") {
    const name = turn.modelIdentity.display_name;
    return name !== null ? `Answered online · ${name}` : "Answered online";
  }
  return "Answered locally";
}
