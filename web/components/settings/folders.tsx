"use client";

import { useCallback, useEffect, useState } from "react";

import type { Registry, Removal, Root } from "@/lib/roots";
import {
  STATE_LABELS,
  nominate,
  previewRemoval,
  readRegistry,
  stateColour,
  unnominate,
} from "@/lib/roots";

/**
 * The folders Askwell may read.
 *
 * `docs/ux/add-source.md` §7. Four states this surface must have and does:
 * loading, empty, listed, and failed-to-read — the last of which says Askwell
 * is not answering rather than rendering an empty list, because an empty list
 * here reads as "you have nominated nothing" and that is a different fact.
 *
 * Removal is confirmed against a consequence the API computed, never one this
 * component guessed. The count of affected sources is a database question, and
 * a confirmation that overstates or understates what it costs is worse than
 * none — someone removing a folder from a list has every reason to fear they
 * are deleting their own files.
 *
 * The path is typed. Until the desktop shell ships `M7-TAURI-FE-182` a browser
 * cannot offer a directory dialog, and this is stated on the screen as a known
 * gap rather than left to be discovered. It is deliberately not a file input:
 * that would upload a copy, and Askwell copies nothing.
 */
export function Folders() {
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [path, setPath] = useState("");
  const [refusal, setRefusal] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<{ root: Root; removal: Removal } | null>(null);

  const load = useCallback(async (): Promise<void> => {
    try {
      setRegistry(await readRegistry());
      setFailure(null);
    } catch (error) {
      setFailure(error instanceof Error ? error.message : "Askwell is not answering.");
    }
  }, []);

  useEffect(() => {
    const first = setTimeout(() => void load(), 0);
    return () => clearTimeout(first);
  }, [load]);

  async function add(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setRefusal(null);
    try {
      await nominate(path);
      setPath("");
      await load();
    } catch (error) {
      setRefusal(error instanceof Error ? error.message : "That folder was not accepted.");
    } finally {
      setBusy(false);
    }
  }

  async function askToRemove(root: Root): Promise<void> {
    try {
      setConfirming({ root, removal: await previewRemoval(root.id) });
    } catch {
      setFailure("Askwell could not say what removing that folder would affect.");
    }
  }

  async function remove(root: Root): Promise<void> {
    setBusy(true);
    try {
      await unnominate(root.id);
      setConfirming(null);
      await load();
    } catch (error) {
      setFailure(error instanceof Error ? error.message : "That folder was not removed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="flex flex-col gap-3">
      <h2 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>
        Folders Askwell may read
      </h2>
      <p className="ask-prose" style={{ color: "var(--muted)" }}>
        Askwell reads your files where they are and never copies them, so it has to be told
        which folders it may open. It can read anything inside a folder you nominate, and
        nothing outside one.
      </p>

      {failure === null ? null : (
        <Note tone="alarm" heading="Askwell is not answering">
          {failure}
        </Note>
      )}

      {registry === null && failure === null ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          Reading the list…
        </p>
      ) : null}

      {registry !== null && registry.count === 0 ? (
        <Note tone="muted" heading="No folders yet">
          Nominate the folder your material lives in. Askwell will index what is inside it
          where it is — nothing is moved, copied or uploaded.
        </Note>
      ) : null}

      {registry?.roots.map((root) => (
        <article
          key={root.id}
          className="flex flex-col gap-1 px-4 py-3"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--rule)",
            borderRadius: "var(--radius)",
          }}
        >
          <div className="flex items-baseline justify-between gap-3">
            <span style={{ fontFamily: "var(--font-app)", fontSize: "var(--t-ui)" }}>
              {root.path}
            </span>
            <span className="ask-micro" style={{ color: stateColour(root.state) }}>
              {STATE_LABELS[root.state]}
            </span>
          </div>
          {root.reason === null ? null : (
            <p style={{ fontSize: "var(--t-meta)", lineHeight: "var(--t-meta-lh)" }}>
              {root.reason}
            </p>
          )}
          {root.warning === null ? null : (
            <p
              style={{
                fontSize: "var(--t-meta)",
                lineHeight: "var(--t-meta-lh)",
                color: "var(--inferred)",
              }}
            >
              {root.warning}
            </p>
          )}

          {confirming?.root.id === root.id ? (
            <div className="mt-2 flex flex-col gap-2">
              <p style={{ fontSize: "var(--t-meta)", lineHeight: "var(--t-meta-lh)" }}>
                {confirming.removal.consequence}
              </p>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void remove(root)}
                  className="ask-navigates px-3 py-1"
                  style={{
                    border: "1px solid var(--alarm)",
                    color: "var(--alarm)",
                    fontSize: "var(--t-ui)",
                  }}
                >
                  Remove it
                </button>
                <button
                  type="button"
                  onClick={() => setConfirming(null)}
                  className="ask-navigates px-3 py-1"
                  style={{ border: "1px solid var(--rule)", fontSize: "var(--t-ui)" }}
                >
                  Keep it
                </button>
              </div>
            </div>
          ) : (
            <div>
              <button
                type="button"
                onClick={() => void askToRemove(root)}
                className="ask-navigates px-3 py-1"
                style={{
                  border: "1px solid var(--rule)",
                  color: "var(--muted)",
                  fontSize: "var(--t-ui)",
                }}
              >
                Remove
              </button>
            </div>
          )}
        </article>
      ))}

      <form onSubmit={(event) => void add(event)} className="flex flex-col gap-2">
        <label
          htmlFor="root-path"
          style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}
        >
          Nominate a folder
        </label>
        <div className="flex gap-2">
          <input
            id="root-path"
            name="path"
            value={path}
            onChange={(event) => setPath(event.target.value)}
            placeholder="/home/you/clients"
            spellCheck={false}
            autoComplete="off"
            className="ask-input flex-1 px-3"
            style={{ fontFamily: "var(--font-app)", fontSize: "var(--t-ui)" }}
          />
          <button
            type="submit"
            disabled={busy || path.trim() === ""}
            className="ask-action-primary px-4"
            style={{ fontSize: "var(--t-ui)" }}
          >
            Nominate
          </button>
        </div>
        <p className="ask-micro">
          Type the whole path. Choosing a folder from a system dialog arrives with the
          desktop application.
        </p>
        {refusal === null ? null : (
          <Note tone="alarm" heading="That folder was not accepted">
            {refusal}
          </Note>
        )}
      </form>

      {registry !== null && registry.removed.length > 0 ? (
        <Note tone="muted" heading="Removed">
          {registry.removed.map((item) => item.path).join(" · ")}. Nothing under these was
          deleted — nominate one again to make its sources readable.
        </Note>
      ) : null}
    </section>
  );
}

function Note({
  tone,
  heading,
  children,
}: {
  tone: "muted" | "alarm";
  heading: string;
  children: React.ReactNode;
}) {
  const colour = tone === "muted" ? "var(--muted)" : "var(--alarm)";
  return (
    <div
      role="status"
      className="ask-carries-meaning px-4 py-3"
      style={{
        background: "var(--surface)",
        borderLeftColor: colour,
        borderRadius: "var(--radius)",
      }}
    >
      <p className="ask-micro" style={{ color: colour }}>
        {heading}
      </p>
      <p className="mt-1" style={{ fontSize: "var(--t-meta)", lineHeight: "var(--t-meta-lh)" }}>
        {children}
      </p>
    </div>
  );
}
