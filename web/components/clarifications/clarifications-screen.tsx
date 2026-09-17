"use client";

import { useEffect, useState } from "react";

import {
  type ClarificationGroup,
  type ClarificationsState,
  NONE_PENDING_COPY,
  fetchClarifications,
  groupSentence,
  totalSentence,
} from "@/lib/clarifications";

/**
 * The clarifications screen. `docs/ux/clarifications.md`, `M3-REVIEW-FE-072`.
 *
 * A single reviewable list, newest source first, grouped by source, with a
 * count per group and a total at the top — never a wizard, never one at a
 * time. §6's "never block" is structural here, not a claim: this screen has
 * no effect on ingestion or on asking a question, so there is nothing for it
 * to hold up even if it fails to load.
 *
 * Answering and skipping are `M3-REVIEW-FE-073`/`-074`'s own territory
 * (Out of Scope, this ticket). What is here is the anatomy those tickets
 * attach controls to — subject, question and evidence, laid out in place so
 * "no navigation" is already true of the list before either is answerable.
 */
export function ClarificationsScreen() {
  const [state, setState] = useState<ClarificationsState | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let live = true;

    fetchClarifications(controller.signal)
      .then((first) => {
        if (live) setState(first);
      })
      .catch((error: unknown) => {
        if (live && !controller.signal.aborted) setFailure(String(error));
      });

    return () => {
      live = false;
      controller.abort();
    };
  }, []);

  return (
    <section className="flex flex-col gap-4">
      <div>
        <h1 style={{ fontSize: "var(--t-display)", lineHeight: "var(--t-display-lh)" }}>
          Clarifications
        </h1>
        {state !== null && state.total > 0 ? (
          <p className="ask-micro mt-1">{totalSentence(state.total)} pending</p>
        ) : null}
      </div>

      {failure !== null ? (
        <p className="ask-prose" style={{ color: "var(--alarm)" }}>
          Askwell is not answering about clarifications.
        </p>
      ) : state === null ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          Reading the queue…
        </p>
      ) : state.total === 0 ? (
        <EmptyClarifications />
      ) : (
        <div className="flex flex-col gap-5">
          {state.groups.map((group) => (
            <SourceGroup key={group.source_id} group={group} />
          ))}
        </div>
      )}
    </section>
  );
}

function EmptyClarifications() {
  return (
    <p
      className="ask-prose px-4 py-3"
      style={{ background: "var(--surface)", borderRadius: "var(--radius)" }}
    >
      {NONE_PENDING_COPY}
    </p>
  );
}

function SourceGroup({ group }: { group: ClarificationGroup }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <h2 style={{ fontSize: "var(--t-ui)" }}>{group.source_name}</h2>
        <span className="ask-micro">{groupSentence(group.count)}</span>
      </div>
      <div className="flex flex-col gap-2">
        {group.items.map((item) => (
          <ClarificationItemRow key={item.id} item={item} />
        ))}
      </div>
    </div>
  );
}

function ClarificationItemRow({ item }: { item: ClarificationGroup["items"][number] }) {
  return (
    <div
      className="flex flex-col gap-1.5 px-4 py-3"
      style={{ background: "var(--surface)", borderRadius: "var(--radius)" }}
    >
      <span className="ask-micro" style={{ fontFamily: "var(--font-mono)" }}>
        {item.subject}
      </span>
      <p className="ask-prose">{item.question}</p>
      {/* Raw for now — the value-distribution rendering `clarifications.md`
          §3 describes is `M3-REVIEW-FE-073`'s "item anatomy" (Out of Scope
          here). `JSON.stringify` is what keeps this honest rather than
          printing "[object Object]" until that ticket formats it properly. */}
      {item.evidence !== null ? (
        <p className="ask-micro" style={{ fontFamily: "var(--font-mono)", color: "var(--muted)" }}>
          {JSON.stringify(item.evidence)}
        </p>
      ) : null}
    </div>
  );
}
