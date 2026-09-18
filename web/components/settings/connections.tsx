"use client";

import { useEffect, useState } from "react";

import { type IngestState, fetchIngest, subscribeIngest } from "@/lib/ingest";

/**
 * Connected databases. `M4-CONN-FE-096`, `docs/ux/settings.md` §4.
 *
 * "Connected databases: N" is a local count, distinct from the "Network
 * activity" figure `docs/ux/settings.md` §4 also names — that one is the
 * egress proxy's own refusal count and stays a measured zero until a permit
 * mechanism exists for a live connection's destination (`docs/decisions.md`,
 * this ticket's date). Folding the two together would make a real, local
 * fact about what the user connected look like the thing C1's zero exists
 * to prove, which it is not.
 */
export function Connections() {
  const [state, setState] = useState<IngestState | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let live = true;

    fetchIngest(controller.signal)
      .then((first) => {
        if (live) setState(first);
      })
      .catch((error: unknown) => {
        if (live && !controller.signal.aborted) setFailure(String(error));
      });

    const stop = subscribeIngest((next) => {
      if (live) setState(next);
    });

    return () => {
      live = false;
      controller.abort();
      stop();
    };
  }, []);

  const connections = (state?.sources ?? []).filter(
    (source) => source.kind === "connection" && source.status !== "deleted",
  );

  return (
    <section className="flex flex-col gap-3">
      <h2 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>
        Connected databases
      </h2>

      {failure !== null ? (
        <p className="ask-prose" style={{ color: "var(--alarm)" }}>
          Askwell is not answering about connected databases.
        </p>
      ) : state === null ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          Loading…
        </p>
      ) : connections.length === 0 ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          None connected. 0 connected databases — separate from the network activity count
          below, which stays zero until a database you connect is explicitly permitted through
          it.
        </p>
      ) : (
        <>
          <p className="ask-micro" style={{ color: "var(--muted)" }}>
            {connections.length} connected database{connections.length === 1 ? "" : "s"}
          </p>
          <ul className="flex flex-col gap-2">
            {connections.map((source) => (
              <li
                key={source.id}
                className="flex flex-wrap items-baseline justify-between gap-3 px-4 py-3"
                style={{
                  background: "var(--surface)",
                  border: "1px solid var(--rule)",
                  borderRadius: "var(--radius)",
                }}
              >
                <span style={{ fontFamily: "var(--font-app)", fontSize: "var(--t-ui)" }}>
                  {source.name ?? "Untitled connection"}
                </span>
                <span className="ask-micro" style={{ color: "var(--muted)" }}>
                  Read access confirmed · write access refused if found
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
