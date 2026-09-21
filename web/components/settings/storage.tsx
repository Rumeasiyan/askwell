"use client";

/**
 * The storage section — `docs/ux/settings.md` §5, `M7-SET-FE-148`.
 *
 * Five displays, per the ticket's own Granularity note, none sharing a
 * fetch or a form with another so one failing does not blank the rest:
 *
 * 1. Per-source index size (`lib/storage.ts` `fetchSourceStorage`).
 * 2. The log budget, current use, and — when the 5%-of-free-disk ceiling
 *    has silently overridden what was configured (issue 484) — that fact,
 *    explained rather than left for the user to notice a number that will
 *    not go up.
 * 3. The interaction retention window. Changing it is a real decisions
 *    record (`askwell.log_budget.set_retention_months`); the prune that
 *    acts on the window is a separate, unbuilt ticket (`M7-LOG-BE-154`),
 *    and this section says so rather than implying the window already
 *    prunes anything.
 * 4. Export and prune. The same honesty: no backend exists yet
 *    (`M7-LOG-BE-155` for export, `M7-LOG-BE-154` for prune), so this is
 *    a stated, disabled entry point — the same pattern `settings.md` §3
 *    already uses for Online AI ahead of Phase 7 — not a button that
 *    fails silently when pressed.
 * 5. What happens at the limit, stated before it happens: ingestion stops
 *    first, asking keeps working. Static, always shown, `docs/audit-log.md`
 *    §3's own headline behaviour.
 */

import { useEffect, useState } from "react";

import { formatBytes } from "@/lib/setup";
import {
  cappedByFreeDisk,
  fetchLogBudget,
  fetchRetentionMonths,
  fetchSourceStorage,
  setLogBudget,
  setRetentionMonths,
  type LogBudgetUsage,
  type SourceStorage,
} from "@/lib/storage";

export function Storage() {
  return (
    <section className="flex flex-col gap-6">
      <h2 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>Storage</h2>

      <PerSourceIndexSize />
      <LogBudget />
      <Retention />
      <ExportAndPrune />
      <AtTheLimit />
    </section>
  );
}

function PerSourceIndexSize() {
  const [rows, setRows] = useState<SourceStorage[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchSourceStorage(controller.signal)
      .then(setRows)
      .catch((thrown: unknown) => {
        if (!controller.signal.aborted) {
          setError(thrown instanceof Error ? thrown.message : "Askwell could not read source storage.");
        }
      });
    return () => controller.abort();
  }, []);

  return (
    <div className="flex flex-col gap-2">
      <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>Index size per source</h3>
      {error !== null ? (
        <p className="ask-micro" style={{ color: "var(--alarm)" }}>
          {error}
        </p>
      ) : null}
      {rows === null && error === null ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          Reading…
        </p>
      ) : null}
      {rows !== null && rows.length === 0 ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          No sources yet.
        </p>
      ) : null}
      {rows !== null && rows.length > 0 ? (
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} style={{ borderBottom: "1px solid var(--rule)" }}>
                <td style={{ padding: "0.35rem 0", fontSize: "var(--t-ui)" }}>{row.name}</td>
                <td className="ask-micro" style={{ padding: "0.35rem 0", color: "var(--muted)" }}>
                  {row.kind}
                </td>
                <td
                  style={{
                    padding: "0.35rem 0",
                    textAlign: "right",
                    fontSize: "var(--t-ui)",
                  }}
                >
                  {row.index_bytes === null ? "Unknown" : formatBytes(row.index_bytes)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <p className="ask-micro" style={{ textTransform: "none" }}>
        Approximate for the vector index — content plus embeddings, not the index structures
        built over them. A connection or database dump is queried in place rather than indexed,
        so its size is unknown rather than zero, as is a source still being indexed.
      </p>
    </div>
  );
}

function LogBudget() {
  const [usage, setUsage] = useState<LogBudgetUsage | null>(null);
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchLogBudget(controller.signal)
      .then((value) => {
        setUsage(value);
        setInput((value.configured_bytes / 1_000_000_000).toFixed(1));
      })
      .catch((thrown: unknown) => {
        if (!controller.signal.aborted) {
          setError(thrown instanceof Error ? thrown.message : "Askwell could not read the log budget.");
        }
      });
    return () => controller.abort();
  }, []);

  const submit = (): void => {
    const gb = Number(input);
    if (!Number.isFinite(gb) || gb <= 0) {
      setError("Enter a number of gigabytes greater than zero.");
      return;
    }
    const requestedBytes = Math.round(gb * 1_000_000_000);
    setSaving(true);
    setError(null);
    setConfirmation(null);
    void setLogBudget(requestedBytes)
      .then((applied) => {
        const consequence =
          applied.used_bytes >= applied.budget_bytes
            ? " Current use is already at or over that — export or prune to bring it back under budget."
            : "";
        setConfirmation(
          `Budget changed to ${formatBytes(applied.configured_bytes)}.${
            cappedByFreeDisk(applied)
              ? ` Effective budget is ${formatBytes(applied.budget_bytes)} — capped by 5% of current free disk.`
              : ""
          }${consequence}`,
        );
        setUsage(applied);
      })
      .catch((thrown: unknown) => {
        setError(thrown instanceof Error ? thrown.message : "Askwell could not change the log budget.");
      })
      .finally(() => setSaving(false));
  };

  return (
    <div className="flex flex-col gap-2">
      <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>Log storage budget</h3>
      <p className="ask-micro" style={{ textTransform: "none" }}>
        The smaller of what you set below and 5% of this machine&apos;s free disk, recalculated
        every time this page loads — a disk filling from something else tightens the budget the
        same way lowering it here would.
      </p>
      {usage !== null ? (
        <>
          <p className="ask-micro" style={{ textTransform: "none" }}>
            Current use: {formatBytes(usage.used_bytes)} of {formatBytes(usage.budget_bytes)}
            {usage.stage === "notice" ? " — approaching the limit." : ""}
            {usage.stage === "hard_limit" ? " — at the limit." : ""}
          </p>
          {cappedByFreeDisk(usage) ? (
            <p className="ask-micro" style={{ textTransform: "none", color: "var(--inferred)" }}>
              You set {formatBytes(usage.configured_bytes)}, but the effective budget is capped at{" "}
              {formatBytes(usage.budget_bytes)} — 5% of current free disk
              ({formatBytes(usage.free_disk_bytes)}).
            </p>
          ) : null}
        </>
      ) : null}
      <div className="flex items-center gap-2">
        <input
          type="number"
          min={0.1}
          step={0.1}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          aria-label="New log budget, in gigabytes"
          style={{ border: "1px solid var(--rule)", padding: "0.25rem 0.5rem", width: "6rem" }}
        />
        <span className="ask-micro">GB</span>
        <button
          type="button"
          onClick={submit}
          disabled={saving || usage === null}
          className="ask-navigates px-2 py-1"
          style={{ border: "1px solid var(--rule)" }}
        >
          {saving ? "Changing…" : "Change budget"}
        </button>
      </div>
      {confirmation !== null ? (
        <p className="ask-micro" style={{ textTransform: "none" }}>
          {confirmation}
        </p>
      ) : null}
      {error !== null ? (
        <p className="ask-micro" style={{ textTransform: "none", color: "var(--alarm)" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

function Retention() {
  const [current, setCurrent] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchRetentionMonths(controller.signal)
      .then((months) => {
        setCurrent(months);
        setInput(String(months));
      })
      .catch((thrown: unknown) => {
        if (!controller.signal.aborted) {
          setError(
            thrown instanceof Error ? thrown.message : "Askwell could not read the retention window.",
          );
        }
      });
    return () => controller.abort();
  }, []);

  const submit = (): void => {
    const months = Number(input);
    if (!Number.isInteger(months) || months <= 0) {
      setError("Enter a whole number of months greater than zero.");
      return;
    }
    setSaving(true);
    setError(null);
    setConfirmation(null);
    void setRetentionMonths(months)
      .then((applied) => {
        setConfirmation(
          `Retention window changed from ${current ?? "its previous value"} to ${applied} months. ` +
            `Recorded in the decisions log. Askwell does not yet prune interactions past this window — ` +
            `that arrives with a later ticket.`,
        );
        setCurrent(applied);
      })
      .catch((thrown: unknown) => {
        setError(
          thrown instanceof Error ? thrown.message : "Askwell could not change the retention window.",
        );
      })
      .finally(() => setSaving(false));
  };

  return (
    <div className="flex flex-col gap-2">
      <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>
        Interaction retention window
      </h3>
      <p className="ask-micro" style={{ textTransform: "none" }}>
        How long a conversation is kept before it is eligible to be archived and pruned. 12
        months by default. Changing this only sets the window — the prune that acts on it is not
        built yet, and nothing is deleted by changing this number.
      </p>
      {current !== null ? (
        <p className="ask-micro" style={{ textTransform: "none" }}>
          Current window: {current} months
        </p>
      ) : null}
      <div className="flex items-center gap-2">
        <input
          type="number"
          min={1}
          step={1}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          aria-label="New retention window, in months"
          style={{ border: "1px solid var(--rule)", padding: "0.25rem 0.5rem", width: "5rem" }}
        />
        <span className="ask-micro">months</span>
        <button
          type="button"
          onClick={submit}
          disabled={saving || current === null}
          className="ask-navigates px-2 py-1"
          style={{ border: "1px solid var(--rule)" }}
        >
          {saving ? "Changing…" : "Change retention window"}
        </button>
      </div>
      {confirmation !== null ? (
        <p className="ask-micro" style={{ textTransform: "none" }}>
          {confirmation}
        </p>
      ) : null}
      {error !== null ? (
        <p className="ask-micro" style={{ textTransform: "none", color: "var(--alarm)" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

function ExportAndPrune() {
  return (
    <div className="flex flex-col gap-2">
      <h3 style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>Export and prune</h3>
      <p className="ask-prose" style={{ color: "var(--muted)" }}>
        Archive the interaction log to a file, then prune what was archived. Not built yet —
        this is where it will be reached from once it is.
      </p>
      <div>
        <button
          type="button"
          disabled
          aria-disabled="true"
          className="px-2 py-1"
          style={{ border: "1px solid var(--rule)", color: "var(--muted)" }}
        >
          Export and prune
        </button>
      </div>
    </div>
  );
}

function AtTheLimit() {
  return (
    <div
      role="status"
      className="ask-carries-meaning px-4 py-3"
      style={{
        background: "var(--surface)",
        borderLeftColor: "var(--inferred)",
        borderRadius: "var(--radius)",
      }}
    >
      <p className="ask-micro" style={{ color: "var(--inferred)" }}>
        At the limit
      </p>
      <p className="mt-1" style={{ fontSize: "var(--t-meta)", lineHeight: "var(--t-meta-lh)" }}>
        Ingestion stops first — new material is refused until space is freed. Asking questions
        keeps working.
      </p>
    </div>
  );
}
