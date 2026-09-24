/**
 * Settings → Online AI → the key. `M8-KEY-FE-174`, `docs/ux/settings.md` §3.
 *
 * The server holds the key (`askwell.provider_key`, `M8-KEY-BE-173`) and
 * never returns it, not even masked: `GET /settings/online-key` says whether
 * one is set and which provider it is for. So this screen cannot show the key
 * again even by mistake. The value exists in the browser only between the
 * paste and the `PUT`, in a password field that is emptied as soon as the
 * save returns, and it travels in the request body, never in a URL.
 *
 * `entryProblem` refuses the paste mistakes worth naming before anything is
 * sent, whitespace above all. The server's own check (`provider_key.validate`)
 * stays the authority; its refusal is shown as it comes, and it never echoes
 * the key.
 */

export interface KeyProvider {
  /** `host:port`, what a conversation's egress grant authorises. */
  destination: string;
  model: string;
}

/** `GET/PUT/DELETE /settings/online-key`, `askwell.online.key_status`. */
export interface KeyStatus {
  set: boolean;
  provider: KeyProvider | null;
  available: boolean;
  unavailable_reason: string | null;
}

/** The server refused because a passphrase is set and not yet entered (`423`). */
export class KeyLocked extends Error {}

async function readStatus(response: Response, verb: string): Promise<KeyStatus> {
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: string } | null;
    const message = body?.error ?? `Askwell could not ${verb} the key (${response.status}).`;
    if (response.status === 423) throw new KeyLocked(message);
    throw new Error(message);
  }
  return (await response.json()) as KeyStatus;
}

export async function fetchKeyStatus(signal?: AbortSignal): Promise<KeyStatus> {
  const response = await fetch("/settings/online-key", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  return readStatus(response, "read");
}

/** Store the key, replacing any held before. In the body, never the URL. */
export async function storeKey(destination: string, model: string, apiKey: string): Promise<KeyStatus> {
  const response = await fetch("/settings/online-key", {
    method: "PUT",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ destination, model, api_key: apiKey }),
  });
  return readStatus(response, "save");
}

export async function removeKey(): Promise<KeyStatus> {
  const response = await fetch("/settings/online-key", {
    method: "DELETE",
    headers: { accept: "application/json" },
  });
  return readStatus(response, "remove");
}

/**
 * Why this entry cannot be saved, or `null` if it can be sent for the
 * server's own check. Named reasons only for the mistakes a paste makes:
 * nothing, only spaces, a space or line break picked up with the key. A
 * padded key is refused rather than trimmed, because trimming would save
 * something other than what was pasted without saying so.
 */
export function entryProblem(destination: string, model: string, apiKey: string): string | null {
  if (destination.trim().length === 0) return "Enter the provider's address, like api.example.com:443.";
  if (/\s/.test(destination)) return "The provider's address has a space in it. Remove it and try again.";
  if (model.trim().length === 0) return "Enter the name of the model to ask for.";
  if (/\s/.test(model)) return "The model name has a space in it. Remove it and try again.";
  if (apiKey.length === 0) return "Paste the key.";
  if (apiKey.trim().length === 0) return "That is only spaces or line breaks, not a key.";
  if (/\s/.test(apiKey)) {
    return (
      "The key has a space or line break in it, often picked up when copying. " +
      "Keys never contain one. Paste it again without it."
    );
  }
  return null;
}

// --- what the screen says ------------------------------------------------------

/** What the key is for, when it is used, and what goes with it. The contents
 * of an online question are the conversation's own statement, made before its
 * first send (`M8-ONLINE-FE-171`), and are not restated here. */
export const KEY_PURPOSE =
  "The key lets Askwell ask a larger model at a provider you choose. It is used only in a " +
  "conversation you have switched to online yourself, and only after that conversation has " +
  "told you exactly what a question will send and you have agreed. It goes to the provider " +
  "address you enter below and nowhere else. Every other conversation, and everything else " +
  "Askwell does, stays on this machine and never uses it.";

/** Askwell's non-involvement in the bill. */
export const KEY_COST =
  "What online AI costs is between you and your provider. Askwell sells nothing, sees no " +
  "bill and takes no part in it.";

/** How it is kept. */
export const KEY_STORAGE =
  "The key is stored encrypted on this machine, never shown again after you save it, never " +
  "logged and never exported. Askwell does not check it with the provider when you save it, " +
  "so a mistyped key shows up only when an online question is refused.";

/** Which providers can take it. */
export const KEY_PROVIDERS = "Any provider that offers an OpenAI-compatible chat API.";

export const KEY_UNSET = "No key is set. Online AI cannot be switched on in any conversation.";

/** The set state. Names the provider, never the key. */
export function keySetLine(provider: KeyProvider | null): string {
  if (provider === null) return "A key is set.";
  return `A key is set for ${provider.destination}, asking for ${provider.model}.`;
}

/** Stated beside Remove, before it is pressed. */
export const REMOVE_CONSEQUENCE =
  "Removing it deletes it from this machine. Any conversation using online AI goes back to " +
  "local at once, and says so.";

/** Stated beside Replace, before it is saved. */
export const REPLACE_CONSEQUENCE =
  "The new key takes the old one's place. If it is for a different provider address, every " +
  "conversation using online AI goes back to local.";

export const SAVED = "Saved. The key will not be shown again.";
export const REPLACED = "Replaced. The new key will not be shown again.";
export const REMOVED = "Removed. The key is no longer on this machine.";

/** A passphrase is set and this session has not entered it. */
export const LOCKED_FIRST =
  "Your passphrase is needed first. The key is encrypted with it, like everything else you " +
  "have protected, and Askwell cannot encrypt a new key until you enter it.";
