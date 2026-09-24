/**
 * Settings → About — `docs/ux/settings.md` §7, `M7-SET-FE-149`.
 *
 * Two kinds of thing live here, and they fail differently.
 *
 * **Bundled texts** — the licence, the third-party notices, the support
 * boundary and the security policy — are copied into `public/` at build time
 * (`scripts/copy-notices.mjs`, `scripts/copy-support.mjs`) and read from the
 * interface's own origin, so they need no network. They are shown inside the
 * page rather than opened in a new tab: the desktop shell denies every
 * `target="_blank"` (`src-tauri/src/main.rs`, `on_new_window`), so a link
 * there is a dead control. A text that fails to load says so; it is never
 * shown partly, because a truncated notices file is a licence problem.
 *
 * **The update check** is `M7-UPDATE-BE-161`'s `/settings/update-check`. The
 * stored answer has three states and this screen shows two of them the same
 * way: `not_asked` and `no` both mean no request is ever made, so both read
 * as off. Only `yes` is on. Nothing here writes an answer except a person
 * pressing the control — an upgrade cannot turn it on, because the backend's
 * default is `not_asked` and this module never sends one on load.
 *
 * **A newer version** (`M7-UPDATE-FE-162`) is a marker in About and nowhere
 * else — no modal, no banner, no badge in the navigation, nothing near an
 * answer. It names only the newest version known, with the date Askwell
 * found it (the feed is a bare version number with no release date, so
 * "found" is the honest word). Dismissing it is stored by the server against
 * that version, so it holds across restarts and returns only when a further
 * version is found. A version already found stays shown after checking is
 * turned off — it is known, and hiding it would pretend otherwise.
 */

/** The one place the repository's address is written in the interface. */
export const REPO_URL = "https://github.com/Rumeasiyan/askwell";
export const ISSUE_URL = `${REPO_URL}/issues/new/choose`;
/** Where each platform's installer is published. Applying an upgrade is
 * that installer's job, never this screen's. */
export const RELEASES_URL = `${REPO_URL}/releases`;

export interface BundledText {
  /** Path on the interface's own origin, under `public/`. */
  path: string;
  /** What the text is, in the words used for it on screen. */
  label: string;
}

export const LICENCE_TEXT: BundledText = { path: "/license.txt", label: "the licence" };
export const NOTICES_TEXT: BundledText = { path: "/notices.md", label: "the third-party notices" };
export const SUPPORT_TEXT: BundledText = { path: "/support.txt", label: "the support boundary" };
export const SECURITY_TEXT: BundledText = { path: "/security-policy.txt", label: "the security policy" };

/**
 * Reads a bundled text in full. Throws rather than returning an empty or
 * partial string — the caller shows the failure, never a blank panel that
 * looks like a short file.
 */
export async function fetchBundledText(text: BundledText, signal?: AbortSignal): Promise<string> {
  const response = await fetch(text.path, {
    ...(signal ? { signal } : {}),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(bundledTextFailure(text, response.status));
  }
  const body = await response.text();
  if (body.trim() === "") {
    throw new Error(bundledTextFailure(text, response.status));
  }
  return body;
}

export function bundledTextFailure(text: BundledText, status: number): string {
  return (
    `Askwell could not open ${text.label} (it answered ${status}). ` +
    `It is bundled with this build, so this means the build is missing a file. ` +
    `The same text is in the source repository.`
  );
}

export type UpdateCheckAnswer = "not_asked" | "yes" | "no";

export interface UpdateCheckState {
  answer: UpdateCheckAnswer;
  last_checked_at: string | null;
  latest_known_version: string | null;
  update_available: boolean;
  last_result: "ok" | "unreachable" | null;
  /** When Askwell first found `latest_known_version`. Null for a version
   * found before this was recorded. */
  latest_known_since: string | null;
  dismissed_version: string | null;
  /** Dismissed for this version or a later one. */
  dismissed: boolean;
}

export interface UpdateMarker {
  version: string;
  /** "Found 3 September 2026", or null when the date was never recorded. */
  found: string | null;
}

/**
 * The marker, or null. One marker, naming the newest known version — never
 * one per version missed. Null when nothing newer is known, including when
 * no check has ever run: that is not a failure and says nothing.
 */
export function updateMarker(state: UpdateCheckState): UpdateMarker | null {
  if (!state.update_available || state.dismissed || state.latest_known_version === null) {
    return null;
  }
  const found =
    state.latest_known_since !== null
      ? `Found ${new Date(state.latest_known_since).toLocaleDateString(undefined, {
          year: "numeric",
          month: "long",
          day: "numeric",
        })}`
      : null;
  return { version: state.latest_known_version, found };
}

/**
 * What happens to the person's material across an upgrade, said before they
 * leave to get one. Every platform's installer (`deploy/linux`,
 * `deploy/macos`, `deploy/windows`) detects the previous installation and
 * replaces only the application files, leaving the data directory
 * untouched, so this is one statement rather than one per platform. If a
 * platform's installer ever stops doing that, this must say so for that
 * platform.
 */
export const UPGRADE_DATA_SAFETY =
  "Install the new version over this one; there is no need to uninstall first. " +
  "The installer replaces Askwell's own program files and leaves your data where it is: " +
  "your indexes, what Askwell remembers, and the audit log are all kept. " +
  "Uninstalling with the option to delete data is the only thing that removes them.";

/** Stated beside "Check now", before it is pressed. */
export const CHECK_NOW_NOTE =
  "Checking now makes that same one request, once, even if weekly checking is off.";

/** The line shown after a check the person asked for. */
export function checkNowOutcome(state: UpdateCheckState): string | null {
  if (state.last_result === "unreachable") {
    return "Askwell could not reach the file, so it does not know whether a newer version exists. Try again later.";
  }
  if (state.last_result !== "ok") {
    return null;
  }
  if (!state.update_available || state.latest_known_version === null) {
    return "This is the newest version.";
  }
  return state.dismissed
    ? `${state.latest_known_version} is available. You dismissed its notice; it returns when a newer version is found.`
    : `${state.latest_known_version} is available. It is shown under the version above.`;
}

/** On only when the person said yes. `not_asked` is off, forever, until
 * they do (`docs/decisions.md`, 2026-09-21). */
export function updateCheckIsOn(state: UpdateCheckState): boolean {
  return state.answer === "yes";
}

/** `docs/ux/settings.md` §7's own sentence — what is sent, stated whole. */
export const UPDATE_CHECK_PAYLOAD =
  "Askwell can check for updates once a week. That is one request for a static file, " +
  "carrying your version number and nothing else. Off by default.";

/** What any request reveals regardless of its payload. Stated because the
 * payload sentence alone would let a reader assume the request is
 * anonymous, and it is not — the server holding the file sees where it came
 * from, as it would for any web request. */
export const UPDATE_CHECK_ADDRESS_NOTE =
  "Like any request on the internet, it also shows the server that holds the file " +
  "your network address.";

export function updateCheckStatus(state: UpdateCheckState): string {
  if (state.answer === "yes") {
    return "On. Askwell checks once a week.";
  }
  if (state.answer === "no") {
    return "Off. You turned it off, and Askwell makes no request.";
  }
  return "Off. It has never been turned on, and Askwell makes no request.";
}

export async function fetchUpdateCheck(signal?: AbortSignal): Promise<UpdateCheckState> {
  const response = await fetch("/settings/update-check", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} reading the update-check setting.`);
  }
  return (await response.json()) as UpdateCheckState;
}

export async function setUpdateCheck(on: boolean): Promise<UpdateCheckState> {
  const response = await fetch("/settings/update-check", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ answer: on ? "yes" : "no" }),
  });
  if (!response.ok) {
    throw new Error(
      `Askwell answered ${response.status} and did not change the update check. ` +
        `It is still ${on ? "off" : "on"}.`,
    );
  }
  return (await response.json()) as UpdateCheckState;
}

/** A check now, regardless of the weekly setting (`M7-UPDATE-BE-161`). */
export async function runUpdateCheck(): Promise<UpdateCheckState> {
  const response = await fetch("/settings/update-check/run", {
    method: "POST",
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} and did not check for updates.`);
  }
  return (await response.json()) as UpdateCheckState;
}

/** Dismiss the marker for the version it showed — not "whatever is newest
 * now", so a version found after the page loaded is never dismissed unseen. */
export async function dismissUpdate(version: string): Promise<UpdateCheckState> {
  const response = await fetch("/settings/update-check/dismiss", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ version }),
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} and did not dismiss the notice. It is still shown.`);
  }
  return (await response.json()) as UpdateCheckState;
}
