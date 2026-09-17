"use client";

import { useEffect, useState } from "react";

import {
  type ClarificationGroup,
  type ClarificationsState,
  type EvidenceDisplay,
  NONE_PENDING_COPY,
  currentInference,
  evidenceDisplay,
  fetchClarifications,
  groupSentence,
  rowCountLabel,
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

/**
 * One question's anatomy: subject, question, evidence, answer, current
 * inference. `M3-REVIEW-FE-073`, `../ux/clarifications.md` §3.
 *
 * Save and Skip render here — equal weight, per that section's own rule —
 * but do nothing yet; wiring them to the API is `M3-REVIEW-FE-074`'s own
 * territory (Out of Scope here).
 */
function ClarificationItemRow({ item }: { item: ClarificationGroup["items"][number] }) {
  const inference = currentInference(item.evidence);
  const evidence = evidenceDisplay(item.evidence);
  const isDiscrete = item.options !== null && item.options.length > 0;

  return (
    <div
      className="flex flex-col gap-2 px-4 py-3"
      style={{ background: "var(--surface)", borderRadius: "var(--radius)" }}
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className="ask-micro" style={{ fontFamily: "var(--font-mono)" }}>
          {item.subject}
        </span>
      </div>
      <p className="ask-prose">{item.question}</p>
      <EvidenceBlock evidence={evidence} />
      {isDiscrete ? (
        <div className="flex flex-wrap gap-2" role="group" aria-label="Choose an answer">
          {(item.options ?? []).map((option) => (
            <button
              key={option}
              type="button"
              className="ask-navigates px-3"
              style={{
                minHeight: "var(--control-height)",
                background: "var(--paper)",
                border: "1px solid var(--rule)",
                borderRadius: "var(--radius)",
                fontFamily: "var(--font-mono)",
                fontSize: "var(--t-ui)",
                color: "var(--ink)",
              }}
            >
              {option}
            </button>
          ))}
        </div>
      ) : (
        <input
          type="text"
          defaultValue={inference ?? ""}
          aria-label={`Your answer: ${item.question}`}
          className="ask-input px-3"
          style={{ fontFamily: "var(--font-text)", fontSize: "var(--t-ui)" }}
        />
      )}
      <div className="flex flex-wrap items-center justify-between gap-3 mt-1">
        <div className="flex gap-2">
          <button
            type="button"
            className="ask-navigates px-4"
            style={{
              minHeight: "var(--control-height)",
              background: "var(--ink)",
              color: "var(--paper)",
              border: "1px solid var(--ink)",
              borderRadius: "var(--radius)",
              fontSize: "var(--t-ui)",
            }}
          >
            Save
          </button>
          <button
            type="button"
            className="ask-navigates px-4"
            style={{
              minHeight: "var(--control-height)",
              background: "var(--ink)",
              color: "var(--paper)",
              border: "1px solid var(--ink)",
              borderRadius: "var(--radius)",
              fontSize: "var(--t-ui)",
            }}
          >
            Skip
          </button>
        </div>
        {inference !== null ? (
          <span className="ask-micro flex items-center gap-1.5" style={{ color: "var(--inferred)" }}>
            <span className="ask-confidence-marker" aria-hidden="true" />I guessed: {inference}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function EvidenceBlock({ evidence }: { evidence: EvidenceDisplay | null }) {
  const mono = { fontFamily: "var(--font-mono)", color: "var(--muted)" } as const;

  if (evidence === null) {
    return (
      <p className="ask-micro" style={mono}>
        No evidence available.
      </p>
    );
  }

  switch (evidence.kind) {
    case "distribution":
      return (
        <p className="ask-micro" style={mono}>
          {rowCountLabel(evidence.rowCount)}. Values:{" "}
          {evidence.values.map((entry) => `${entry.value} (${entry.count.toLocaleString("en-US")})`).join(" · ")}
          {evidence.remainderCount > 0
            ? ` · ${evidence.remainderCount.toLocaleString("en-US")} more`
            : ""}
        </p>
      );
    case "passage":
      return evidence.samples.length > 0 ? (
        <div className="flex flex-col gap-1">
          {evidence.samples.map((sample, index) => (
            <p key={index} className="ask-micro" style={mono}>
              {sample.document}
              {sample.page !== null ? `, p. ${sample.page}` : ""} — {sample.text}
            </p>
          ))}
        </div>
      ) : (
        <p className="ask-micro" style={mono}>
          No evidence available.
        </p>
      );
    case "poor_scan":
      return evidence.extracted.length > 0 ? (
        <div className="flex flex-col gap-1">
          <p className="ask-micro" style={mono}>
            {evidence.pages.length} of {evidence.totalPages} page(s) scanned poorly.
          </p>
          {evidence.extracted.map((sample, index) => (
            <p key={index} className="ask-micro" style={mono}>
              p. {sample.page} — {sample.text}
            </p>
          ))}
        </div>
      ) : (
        <p className="ask-micro" style={mono}>
          No evidence available.
        </p>
      );
    case "contradiction":
      return (
        <div className="flex flex-col gap-1">
          {evidence.passages.map((passage, index) => (
            <p key={index} className="ask-micro" style={mono}>
              {passage.document} says {passage.value}
              {passage.date !== null ? ` (${passage.date})` : ""} — {passage.text}
            </p>
          ))}
        </div>
      );
    case "unavailable":
      return (
        <p className="ask-micro" style={mono}>
          No evidence available{evidence.reason !== "" ? ` — ${evidence.reason}` : ""}.
        </p>
      );
  }
}
