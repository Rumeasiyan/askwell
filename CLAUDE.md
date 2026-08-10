@AGENTS.md

# Claude-specific notes

Everything about how to work in this repository lives in `AGENTS.md`, imported above. Do not add rules here — a rule that exists in two files drifts, and the copy Claude reads will quietly win.

**Subagents do not inherit this context.** A subagent launched via the Agent tool starts with a fresh context and will not have read `AGENTS.md`. When delegating, restate inline whatever constraint applies to the delegated work — especially:

- C2 (model SQL goes through `sqlglot`; regex filtering is never acceptable)
- C1 (no runtime network calls, including in generated code and dependencies)
- C4 (abstention over invention; do not weaken abstention eval tests to make a change pass)

A subagent that has not been told these will happily write a regex SQL filter or add a CDN link, and it will look correct in review.

**Do not use subagents or workflows unless asked.** This is a documentation-heavy repository where the main thread's accumulated context is the useful thing; fanning out loses it.

**`PRD.md` §11 is a hard stop, not a prompt for a reasonable default.** Five product questions are unanswered. If a task depends on one, ask — the cost of a wrong guess here is a phase of work built against the wrong assumption.
