"use client";

/**
 * About — `docs/ux/settings.md` §7. Built up by `M7-DOC-DOC-163` (notices),
 * `M7-DOC-DOC-164` (the support boundary and the security route) and
 * completed by `M7-SET-FE-149`.
 *
 * Every bundled text — licence, notices, support boundary, security policy —
 * is read from the interface's own origin and shown here, in full, in a
 * scrollable panel (`lib/about.ts`). Not a link to a new tab: the desktop
 * shell denies every `target="_blank"`, so a link there is a dead control,
 * and a notices file that could only be opened in a browser tab is not
 * "reachable in full" inside the product.
 *
 * External addresses — the source and the issue tracker — are shown as text
 * that can be selected and copied, because offline (and in the desktop
 * shell, always) they cannot be opened from here. An "Open" link is offered
 * beside them only in a browser, where it works when there is a network.
 *
 * The support boundary leads the report route, shown before the address
 * that opens an issue, so what is and is not answered is read first. The
 * security route is its own row, never folded in: a vulnerability filed as
 * a public issue is already disclosed.
 *
 * Update checking is `M7-UPDATE-BE-161`'s real setting, off unless the
 * person turned it on. The control states the payload before it is pressed.
 */

import { useEffect, useState, useSyncExternalStore } from "react";

import {
  fetchBundledText,
  fetchUpdateCheck,
  ISSUE_URL,
  LICENCE_TEXT,
  NOTICES_TEXT,
  REPO_URL,
  SECURITY_TEXT,
  setUpdateCheck,
  SUPPORT_TEXT,
  UPDATE_CHECK_ADDRESS_NOTE,
  UPDATE_CHECK_PAYLOAD,
  updateCheckIsOn,
  updateCheckStatus,
  type BundledText,
  type UpdateCheckState,
} from "@/lib/about";
import { isNative } from "@/lib/native";
import { VERSION } from "@/lib/version";

const outlined = { border: "1px solid var(--rule)" } as const;

/** Whether this is the desktop shell cannot change while the page is open. */
const neverChanges = () => () => {};

export function About() {
  return (
    <section className="flex flex-col gap-6">
      <h2 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>About</h2>

      <dl className="ask-prose flex flex-col gap-3">
        <div className="flex items-baseline gap-2">
          <dt style={{ color: "var(--muted)" }}>Version</dt>
          <dd>{VERSION}</dd>
        </div>
        <div className="flex flex-col gap-1">
          <div className="flex items-baseline gap-2">
            <dt style={{ color: "var(--muted)" }}>Licence</dt>
            <dd>Apache-2.0</dd>
          </div>
          <dd>
            <BundledTextDisclosure text={LICENCE_TEXT} summary="Read the licence in full" />
          </dd>
        </div>
        <div className="flex flex-col gap-1">
          <dt style={{ color: "var(--muted)" }}>Source</dt>
          <dd>
            <Address url={REPO_URL} label="source repository" />
          </dd>
        </div>
        <div className="flex flex-col gap-1">
          <dt style={{ color: "var(--muted)" }}>Notices</dt>
          <dd>
            <BundledTextDisclosure
              text={NOTICES_TEXT}
              summary="Third-party notices and licences, including the bundled model weights"
            />
          </dd>
        </div>
      </dl>

      <ReportAProblem />
      <SecurityProblem />
      <UpdateChecking />
    </section>
  );
}

function ReportAProblem() {
  return (
    <div className="flex flex-col gap-2">
      <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>Report a problem</h3>
      <p className="ask-prose" style={{ color: "var(--muted)" }}>
        Read what one maintainer can and cannot answer first. It is bundled with Askwell, so it
        reads without a network.
      </p>
      <BundledTextPanel text={SUPPORT_TEXT} />
      <p className="ask-prose">
        Then open an issue. Include the version above, your platform, your profile and a copied
        trace.
      </p>
      <Address url={ISSUE_URL} label="issue tracker" />
    </div>
  );
}

function SecurityProblem() {
  return (
    <div className="flex flex-col gap-2">
      <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>Security problem</h3>
      <p className="ask-prose">
        Report it privately, not as an issue. An issue is public, so a security problem filed
        there is already disclosed.
      </p>
      <BundledTextDisclosure text={SECURITY_TEXT} summary="How to report a security problem" />
    </div>
  );
}

function UpdateChecking() {
  const [state, setState] = useState<UpdateCheckState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchUpdateCheck(controller.signal)
      .then(setState)
      .catch((thrown: unknown) => {
        if (!controller.signal.aborted) {
          setError(thrown instanceof Error ? thrown.message : "Askwell could not read the update check.");
        }
      });
    return () => controller.abort();
  }, []);

  function change(on: boolean) {
    setSaving(true);
    setError(null);
    setUpdateCheck(on)
      .then(setState)
      .catch((thrown: unknown) => {
        setError(thrown instanceof Error ? thrown.message : "Askwell did not change the update check.");
      })
      .finally(() => setSaving(false));
  }

  return (
    <div className="flex flex-col gap-2">
      <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>Update checking</h3>
      <p className="ask-prose">{UPDATE_CHECK_PAYLOAD}</p>
      <p className="ask-prose" style={{ color: "var(--muted)" }}>
        {UPDATE_CHECK_ADDRESS_NOTE}
      </p>
      {state === null && error === null ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          Reading…
        </p>
      ) : null}
      {state !== null ? (
        <>
          <label className="ask-prose flex items-center gap-2">
            <input
              type="checkbox"
              checked={updateCheckIsOn(state)}
              disabled={saving}
              onChange={(event) => change(event.target.checked)}
            />
            Check for updates once a week
          </label>
          <p className="ask-micro" style={{ color: "var(--muted)", textTransform: "none" }}>
            {saving ? "Saving…" : updateCheckStatus(state)}
          </p>
        </>
      ) : null}
      {error !== null ? (
        <p className="ask-micro" style={{ color: "var(--alarm)", textTransform: "none" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** An address shown as text first, so it can be copied when it cannot be
 * opened — offline, or in the desktop shell, which opens nothing outside
 * Askwell. */
function Address({ url, label }: { url: string; label: string }) {
  const [copied, setCopied] = useState<"idle" | "copied" | "failed">("idle");
  // The page is prerendered where no shell exists; the server snapshot says
  // so, and the client's own answer takes over after hydration.
  const native = useSyncExternalStore(neverChanges, isNative, () => false);

  function copy() {
    void navigator.clipboard.writeText(url).then(
      () => setCopied("copied"),
      () => setCopied("failed"),
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <code style={{ userSelect: "all", overflowWrap: "anywhere" }} aria-label={`Address of the ${label}`}>
          {url}
        </code>
        <button type="button" className="ask-navigates px-2 py-1" style={outlined} onClick={copy}>
          {copied === "copied" ? "Copied" : "Copy address"}
        </button>
        {native ? null : (
          <a href={url} target="_blank" rel="noreferrer">
            Open
          </a>
        )}
      </div>
      {copied === "failed" ? (
        <p className="ask-micro" style={{ color: "var(--alarm)", textTransform: "none" }}>
          Could not copy. Select the address and copy it.
        </p>
      ) : null}
    </div>
  );
}

/** Closed until asked for; read only once opened, then shown whole. */
function BundledTextDisclosure({ text, summary }: { text: BundledText; summary: string }) {
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="ask-navigates" style={{ cursor: "pointer" }}>
        {summary}
      </summary>
      {open ? (
        <div className="mt-2">
          <BundledTextPanel text={text} />
        </div>
      ) : null}
    </details>
  );
}

/** The whole text, scrollable, never truncated. A failure to read it is
 * named, never a blank panel that could pass for a short file. */
function BundledTextPanel({ text }: { text: BundledText }) {
  const [body, setBody] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchBundledText(text, controller.signal)
      .then(setBody)
      .catch((thrown: unknown) => {
        if (!controller.signal.aborted) {
          setError(thrown instanceof Error ? thrown.message : `Askwell could not open ${text.label}.`);
        }
      });
    return () => controller.abort();
  }, [text]);

  if (error !== null) {
    return (
      <p className="ask-micro" style={{ color: "var(--alarm)", textTransform: "none" }}>
        {error}
      </p>
    );
  }
  if (body === null) {
    return (
      <p className="ask-prose" style={{ color: "var(--muted)" }}>
        Reading…
      </p>
    );
  }
  return (
    <pre
      tabIndex={0}
      aria-label={`${text.label}, in full`}
      className="px-4 py-3"
      style={{
        maxHeight: "24rem",
        overflowY: "auto",
        whiteSpace: "pre-wrap",
        overflowWrap: "anywhere",
        fontSize: "var(--t-meta)",
        lineHeight: "var(--t-meta-lh)",
        background: "var(--surface)",
        borderRadius: "var(--radius)",
        ...outlined,
      }}
    >
      {body}
    </pre>
  );
}
