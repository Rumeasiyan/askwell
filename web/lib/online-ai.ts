/**
 * Settings → Online AI. `M7-SET-FE-150`, `docs/ux/settings.md` §3.
 *
 * Everything here is words. Since `M8-ONLINE-FE-171` online AI is switched
 * on per conversation, from the conversation (`lib/online-conversation.ts`),
 * so this section has no switch at all: a switch here would read as the
 * global setting the ticket forbids. There is no field and no request.
 * `M8-KEY-FE-174` adds the key here.
 *
 * The copy follows `docs/decisions.md` 2026-09-23 — online AI uses a key the
 * person brings from their own provider, and Askwell sells nothing — not
 * the ticket's original wording, which predated that decision and promised
 * the opposite ("never asks for an API key", "paid by credit"). No price is
 * described because there is none to describe.
 */

/** Where it is turned on, since it is not here. */
export const ONLINE_AI_WHERE =
  "There is no switch here. Online AI is turned on for one conversation at a time, with " +
  "the switch beside that conversation's Ask button, and every new conversation starts local.";

/** What it will be, in plain terms. */
export const ONLINE_AI_WHAT =
  "A larger cloud model, for a question the model on this machine finds too hard. " +
  "Askwell works completely without it — it is an escape hatch for a hard question, not a tier.";

/** Per conversation, never global. */
export const ONLINE_AI_PER_CONVERSATION =
  "It is chosen per conversation. A conversation is either local or online, and you " +
  "switch it yourself. There is no setting that turns it on everywhere, so there is " +
  "nothing to forget about.";

/** The key, and who the bill is between. */
export const ONLINE_AI_KEY =
  "It will use an API key from a provider you already pay. Askwell sells nothing and takes " +
  "no part in what it costs — the account, the provider and the bill are yours. The key will " +
  "be stored encrypted on this machine, never logged and never exported. Nothing on this " +
  "screen asks for a key today, because there is nothing yet that could use one.";

/** The payload statement is made in the conversation, before the first
 * send. Its wording is not decided yet (issue 737), and until it is, nothing is
 * sent, which this says rather than guessing what the statement will be. */
export const ONLINE_AI_PAYLOAD =
  "Exactly what leaves this machine is stated in the conversation before anything is " +
  "sent, never after. That statement has not been written yet, so online AI sends nothing " +
  "today. Until then, nothing leaves.";
