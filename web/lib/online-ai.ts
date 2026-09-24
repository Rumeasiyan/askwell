/**
 * Settings → Online AI, before it exists. `M7-SET-FE-150`,
 * `docs/ux/settings.md` §3 and §8's "Online AI, before M8" row.
 *
 * Everything here is words. The section is inert: there is no endpoint
 * behind it, no field in it, and no state that can become "on" — the only
 * thing a click can change is whether the not-available statement is shown.
 * M8 (`M8-KEY-FE-174`) fills the section in rather than adding a new one.
 *
 * The copy follows `docs/decisions.md` 2026-09-23 — online AI uses a key the
 * person brings from their own provider, and Askwell sells nothing — not
 * the ticket's original wording, which predated that decision and promised
 * the opposite ("never asks for an API key", "paid by credit"). No price is
 * described because there is none to describe.
 */

export const ONLINE_AI_STATUS = "Off. Not available yet.";

/** What it will be, in plain terms. */
export const ONLINE_AI_WHAT =
  "A larger cloud model, for a question the model on this machine finds too hard. " +
  "Askwell works completely without it — it is an escape hatch for a hard question, not a tier.";

/** Per conversation, never global. */
export const ONLINE_AI_PER_CONVERSATION =
  "It will be chosen per conversation. A conversation is either local or online, and you " +
  "switch it yourself. There will be no setting that turns it on everywhere, so there is " +
  "nothing to forget about.";

/** The key, and who the bill is between. */
export const ONLINE_AI_KEY =
  "It will use an API key from a provider you already pay. Askwell sells nothing and takes " +
  "no part in what it costs — the account, the provider and the bill are yours. The key will " +
  "be stored encrypted on this machine, never logged and never exported. Nothing on this " +
  "screen asks for a key today, because there is nothing yet that could use one.";

/** Placeholder for the payload statement, which M8 states exactly. Says
 * when it will be stated rather than guessing what it will say. */
export const ONLINE_AI_PAYLOAD =
  "Exactly what leaves this machine will be stated here, and again in the conversation " +
  "before anything is sent — never after. Until then, nothing leaves.";

/** Shown when someone tries to turn it on. No waiting list, no email
 * field: there is nothing to sign up for. */
export const ONLINE_AI_NOT_AVAILABLE =
  "Online AI is not available yet, so it cannot be turned on. There is nothing to sign up " +
  "for and no list to join. When it exists it will appear here, still off until you choose " +
  "it for a conversation.";

/** What the section holds after any number of attempts to enable it: never
 * on, and the statement shown once someone has tried. */
export type OnlineAiView = { readonly on: false; readonly notice: string | null };

export const ONLINE_AI_INITIAL: OnlineAiView = { on: false, notice: null };

export function attemptToEnable(): OnlineAiView {
  return { on: false, notice: ONLINE_AI_NOT_AVAILABLE };
}
