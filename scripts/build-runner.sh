#!/usr/bin/env bash
# Askwell build runner. Specification: docs/build-runner.md — that document is
# authoritative; this script implements it and does not restate it.
#
# The runner is a driver, not a second rulebook. Everything it tells a session
# comes from AGENTS.md, docs/backlog/, docs/decisions.md and the tracker, or is
# about running the pipeline itself.
#
# Targets bash 3.2 (macOS ships it; architecture.md §2.1 puts macOS in v1).

set -Eeuo pipefail
# pipefail matters: agent output is piped through tee constantly, and without it
# the status read is tee's, which is always 0.

# --- re-exec from an immutable copy, before anything else --------------------
# Bash reads a script incrementally by byte offset. Editing this file mid-run
# resumes it mid-token, which looks like data corruption rather than a
# self-inflicted wound.
if [ -z "${RUNNER_IMMUTABLE:-}" ]; then
  RUNNER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  _copy="$(mktemp)"; cat "${BASH_SOURCE[0]}" > "$_copy"; chmod +x "$_copy"
  RUNNER_IMMUTABLE=1 RUNNER_ROOT="$RUNNER_ROOT" RUNNER_TMP="$_copy" \
    exec "$_copy" "$@"
fi
cd "$RUNNER_ROOT"
# BASH_SOURCE now points at the temp copy, which is why the real root travels
# in the environment.

# --- configuration (docs/build-runner.md §10) --------------------------------
: "${AGENT_BIN:=claude}"
: "${BUILD_MODEL:=}"        # empty means the CLI's own default; never invent one
: "${BUILD_EFFORT:=}"
: "${AUDIT_MODEL:=}"
: "${AUDIT_EFFORT:=}"
: "${DOC_MODEL:=}"
: "${DOC_EFFORT:=}"
: "${MAX_REPAIR:=2}"
: "${RUN_AUDIT:=1}"
: "${RUN_DOC:=1}"
: "${STOP_AFTER_EACH:=1}"
: "${SPEND_CEILING:=}"      # unset refuses to start — see guards.sh
: "${DRY_RUN:=0}"
: "${FORCE:=0}"
: "${AGENT_TIMEOUT:=3600}"
: "${RUNNER_STATE:=.build-runner}"

BACKLOG_DIR="docs/backlog"
MANUAL_TEST_DIR="docs/manual-tests"
REPO_SLUG="Rumeasiyan/askwell"
PROTECTED_BRANCH="main"
SELF="scripts/build-runner.sh"   # $0 is the temp copy after re-exec; never show it

# shellcheck source=scripts/guards.sh
. "$RUNNER_ROOT/scripts/guards.sh"

BOLD=""; DIM=""; RESET=""
if [ -t 1 ]; then BOLD="$(printf '\033[1m')"; DIM="$(printf '\033[2m')"; RESET="$(printf '\033[0m')"; fi

say()  { printf '%s\n' "$*"; }
head2(){ printf '\n%s== %s ==%s\n' "$BOLD" "$*" "$RESET"; }
die()  { printf '\n%sSTOP:%s %s\n' "$BOLD" "$RESET" "$*" >&2; exit 1; }

cleanup() { [ -n "${RUNNER_TMP:-}" ] && rm -f "$RUNNER_TMP"; }
on_err()  { printf '\n%sFAILED%s in phase "%s". Logs: %s\n' \
              "$BOLD" "$RESET" "${PHASE:-startup}" "$RUNNER_STATE/logs" >&2; }
trap on_err ERR
trap cleanup EXIT
PHASE="startup"

# --- argument parsing --------------------------------------------------------
TICKET_ARG=""; LIST_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --list)  LIST_ONLY=1 ;;
    --dry)   DRY_RUN=1 ;;
    --force) FORCE=1 ;;
    --help|-h)
      cat <<'USAGE'
scripts/build-runner.sh [TICKET_ID] [--list] [--dry] [--force]

  no args     next unbuilt ticket in dependency order
  TICKET_ID   that ticket specifically
  --list      print the resolved queue and exit
  --dry       render prompts, run preflight, print, and exit before any agent call
  --force     rebuild a ticket already marked done

Configuration is environment variables — see docs/build-runner.md §10.
SPEND_CEILING is required; unset refuses to start.
USAGE
      exit 0 ;;
    -*) die "unknown flag: $1  (try --help)" ;;
    *)  TICKET_ARG="$1" ;;
  esac
  shift
done

# --- backlog parsing ---------------------------------------------------------
# Work items are markdown sections in docs/backlog/M*.md, not tracker issues.
# Tracker issues are deferred work and open questions (docs/build-runner.md §5).

ticket_ids() {
  grep -rhoE '^### [A-Z0-9.]+-[A-Z]+-[A-Z]+-[0-9]{3}[a-z]?' "$BACKLOG_DIR"/M*.md \
    | sed 's/^### //'
}

ticket_file() {
  grep -rlE "^### $1( |$)" "$BACKLOG_DIR"/M*.md 2>/dev/null | head -1
}

# Print one ticket's body: from its own heading to the next ### heading.
ticket_body() {
  local id="$1" f; f="$(ticket_file "$id")"
  [ -n "$f" ] || return 1
  awk -v id="$id" '
    $0 ~ "^### " id "( |$)" { on=1 }
    on && /^### / && $0 !~ "^### " id "( |$)" && seen { exit }
    on { print; if ($0 ~ "^### " id "( |$)") seen=1 }
  ' "$f"
}

ticket_field() {   # ticket_field <id> <label>  -> the text after "**Label:**"
  ticket_body "$1" | grep -m1 -oE "\*\*$2:\*\*.*" | sed "s/\*\*$2:\*\*[[:space:]]*//"
}

ticket_deps() {
  local raw; raw="$(ticket_field "$1" 'Dependencies')"
  printf '%s' "$raw" | grep -oE '[A-Z0-9.]+-[A-Z]+-[A-Z]+-[0-9]{3}[a-z]?' || true
}

# Estimates are hour ranges. The guard takes the HIGH end: taking the low end
# under-protects, and a ceiling that under-protects is not a ceiling.
ticket_estimate_hours() {
  ticket_field "$1" 'Estimate' | grep -oE '[0-9]+([.][0-9]+)?' | tail -1
}

ticket_is_blocked() { ticket_body "$1" | grep -q '\[BLOCKED\]'; }

# No copy-review marker exists in the ticket format yet (docs/build-runner.md §9,
# open decision 3). Detection is from the ticket body so it works the moment the
# marker is added — never from a list in this script, which would be a second
# source of truth that drifts.
ticket_needs_copy_review() {
  ticket_body "$1" | grep -qiE '^\*\*Human review:\*\*.*copy'
}

is_done()  { [ -f "$RUNNER_STATE/done/$1" ]; }
mark_done(){ mkdir -p "$RUNNER_STATE/done"; : > "$RUNNER_STATE/done/$1"; }

deps_satisfied() {
  local d
  for d in $(ticket_deps "$1"); do
    is_done "$d" || return 1
  done
  return 0
}

next_ticket() {
  local id
  for id in $(ticket_ids); do
    is_done "$id" && continue
    ticket_is_blocked "$id" && continue
    deps_satisfied "$id" || continue
    printf '%s' "$id"; return 0
  done
  return 1
}

# --- preflight ---------------------------------------------------------------
# Collect every failure, then exit once with all of them. Failing on the first
# problem makes the operator run this four times.
FAILURES=""
fail() { FAILURES="${FAILURES}
  - $1"; }

preflight() {
  PHASE="preflight"
  command -v git >/dev/null || fail "git not on PATH."
  command -v "$AGENT_BIN" >/dev/null || fail "agent CLI '$AGENT_BIN' not on PATH. Set AGENT_BIN."
  command -v gh >/dev/null || fail "gh not on PATH — needed for issues and PRs. Install the GitHub CLI."
  command -v gh >/dev/null && { gh auth status >/dev/null 2>&1 || fail "gh is not authenticated. Run: gh auth login"; }

  [ -z "$(git status --porcelain)" ] || \
    fail "Working tree is dirty; the runner will not build on top of uncommitted work.
      Run: git status --short   then commit or stash."

  local branch; branch="$(git rev-parse --abbrev-ref HEAD)"
  [ "$branch" != "$PROTECTED_BRANCH" ] || \
    fail "On '$PROTECTED_BRANCH'. The runner creates its own branch and never commits here.
      Run: git checkout -b <type>/<slug>   or let the runner create it once this check is the only failure."

  [ -n "$SPEND_CEILING" ] || \
    fail "SPEND_CEILING is not set. An unattended queue with no ceiling is what this guard exists for.
      Run: SPEND_CEILING=<hours> $SELF"

  [ -d "$BACKLOG_DIR" ] || fail "$BACKLOG_DIR not found — is this the Askwell repository?"

  # The gate does not exist yet; M0 creates it. Absence is reported, never treated
  # as a pass (docs/build-runner.md §7.1).
  if [ ! -e "compose.yaml" ] && [ ! -e "api/pyproject.toml" ]; then
    say "${DIM}note: the product gate does not exist yet — M0 creates it."
    say "      Gate commands will be skipped with a warning, not treated as passing.${RESET}"
  fi

  if [ -n "$FAILURES" ]; then
    printf '\n%sPreflight failed:%s%s\n\n' "$BOLD" "$RESET" "$FAILURES" >&2
    exit 1
  fi
}

# --- prompt rendering --------------------------------------------------------
# Quoted heredocs only. An unquoted heredoc runs backticks and $(...) inside the
# prompt text and substitutes an EMPTY STRING, so a ticket builds from a prompt
# quietly missing whatever those backticks wrapped. These tickets are dense with
# backticks. bash -n does not catch it.

shared_block() {
  cat <<'SHARED'
## How work happens here

`AGENTS.md` is the single source of truth for this repository. **Read it before deciding
anything.** Its §3 holds constraints C1–C10. Breaking one does not fail a test — it destroys
something or creates exposure. The ones a passing gate will not catch:

- **C2** — model-generated SQL goes through `sqlglot`; regex filtering is never acceptable.
- **C3** — an imported dump is untrusted code and loads only into the isolated sandbox.
- **C5** — abstention over invention. Never weaken an abstention test to make a change pass.
- **C10** — web search is an escalation the user performs, never a fallback.

**Read `docs/decisions.md` before changing anything that looks wrong.** Odd-looking code here
is usually a recorded decision. Disagreement gets recorded, not silently reversed.

**Log what you do not fix now** as a GitHub issue in the house format from `AGENTS.md` §8:
what it is · why it matters · where it surfaced · options with a recommendation. A closing
summary is discarded and the work is lost.

**Write new decisions back to `docs/decisions.md`**, with the *why* longer than the *what*.

**Resolve any open question naming this ticket as owner** before it closes — answered,
re-owned, or escalated.

**Your training data may be older than this stack.** Do not use an API you cannot confirm
against what is actually installed. `AGENTS.md` §4 requires registry verification for model,
weight and traineddata names — that rule exists because it was broken twice.

**Prefer what exists**, in order: something already in this repo; an already-installed
package; the framework natively; then a new maintained package, version looked up from the
registry and checked for compatibility, not just currency.

**Never hand-roll authentication, cryptography, or permission checks.**
SHARED
}

owned_work() {   # tracker items and open questions naming this ticket
  local id="$1" issues
  issues="$(gh issue list --repo "$REPO_SLUG" --state open --search "$id" \
              --json number,title --template \
              '{{range .}}- #{{.number}} {{.title}}{{"\n"}}{{end}}' 2>/dev/null || true)"
  if [ -n "$issues" ]; then printf '%s\n' "$issues"
  else printf 'none\n'; fi
}

render_build_prompt() {
  local id="$1" out="$2"
  {
    cat <<'HDR'
Implement exactly one backlog ticket in the Askwell repository.

HDR
    shared_block
    cat <<'MID'

## The ticket — implement this and nothing else

MID
    ticket_body "$id"
    cat <<'DOD'

## Also part of the definition of done

Open tracker items and questions naming this ticket. Resolve or explicitly re-own each
before this ticket closes:

DOD
    owned_work "$id"
    cat <<'TAIL'

## How to do it

Follow the workflow in `AGENTS.md` §9. Commit format is Conventional Commits with the phase
in brackets, per §6. Write tests covering this ticket's stated acceptance criteria — §4
requires them *first* for retrieval, SQL validation and the agent loop.

Decide version and changelog impact per `AGENTS.md` §7, and if the version moves, add the
`CHANGELOG.md` entry in the same change.

**Implement only this ticket.** If it depends on something that has not been built, say so
and stop. Do not silently stub it — a stub that looks finished is worse than an honest halt.

Do not commit, do not branch, do not open a pull request. The runner does that.
TAIL
  } > "$out"
}

render_audit_prompt() {
  local id="$1" out="$2"
  {
    cat <<'HDR'
Audit one ticket's implementation in the Askwell repository.

**You did not write this code. Do not assume it is correct.**

HDR
    shared_block
    cat <<'MID'

## The ticket that was implemented

MID
    ticket_body "$id"
    cat <<'TAIL'

## What to check

Check the working tree against **this ticket's own** acceptance criteria, edge cases and
constraint checklist. This is not a generic code review.

Hunt specifically for:
- reinvention of something already in this repository
- APIs that do not exist in the installed versions
- acceptance criteria with no test covering them
- silent stubs presented as finished work
- any constraint in `AGENTS.md` §3 that a passing gate would not catch

**Do not run the full test suite. Do not end your turn waiting on a background task.**
The runner re-runs the gate itself immediately after you finish, so doing it here is
redundant — and a turn that ends on a background task loses your verdict entirely.

File anything you find but do not fix as a GitHub issue, in the house format, naming this
ticket.

**End your final message with exactly one of these lines, and nothing after it:**

AUDIT: PASS
AUDIT: FAIL
TAIL
  } > "$out"
}

render_doc_prompt() {
  local id="$1" out="$2"
  {
    cat <<'HDR'
Write the manual test document for one implemented ticket in the Askwell repository.

HDR
    shared_block
    cat <<'MID'

## The ticket

MID
    ticket_body "$id"
    cat <<'TAIL'

## What to write

Write to `docs/manual-tests/<TICKET-ID>.md`, using the ticket id as the filename.

**Start from a cold start and walk the whole path as a user would** — launch the application,
complete first-run if it applies, and navigate by clicking. **Never write "go to /settings".
Never write "call this endpoint".** That is not pedantry: direct-jump testing never catches
broken navigation, lost session state, or dead ends — and re-walking the path on every ticket
is how an upstream regression surfaces on the next ticket instead of in someone's install.

Expand this ticket's own cold-start walkthrough into something a non-technical person can
follow. Number the steps. After each, say what they should see, in observable terms — "the
answer shows supplier-agreement-2024.pdf, page 14" is testable by looking; "the citation is
persisted correctly" is not.

**Read the code on disk.** Test what exists, not what the ticket assumed would be built.

End with a **Known gaps** section listing what is deliberately not built yet, so it is not
reported as a defect.
TAIL
  } > "$out"
}

# Cheap sentinels beat discipline. If a heredoc breaks, the prompt loses text
# silently — this refuses to run rather than building from a damaged prompt.
assert_prompt_intact() {
  local p="$1" id="$2" phrase
  for phrase in "$id" "AGENTS.md" "docs/decisions.md" "Acceptance Criteria"; do
    grep -qF -- "$phrase" "$p" || die "PROMPT DAMAGED: '$phrase' missing from $p
       A heredoc has broken. Do not run until the prompt renders whole."
  done
  [ "$(wc -c < "$p")" -gt 1500 ] || die "PROMPT DAMAGED: $p is implausibly short."
}

# --- agent invocation --------------------------------------------------------
run_agent() {   # run_agent <lineage> <prompt-file> <log-file> [model] [effort]
  local lineage="$1" prompt="$2" log="$3" model="$4" effort="$5"
  # Audit and doc lineages reset per milestone: a single session across 198
  # tickets carries context from work three milestones old, and a stale auditor
  # is worse than a forgetful one. The property that matters — it did not write
  # the code — survives a reset.
  local sid="$RUNNER_STATE/session/${lineage}.${MILESTONE:-none}.id"
  local args; args="--print"
  [ -n "$model" ]  && args="$args --model $model"
  [ -n "$effort" ] && args="$args --effort $effort"
  if [ "$lineage" != "build" ] && [ -s "$sid" ]; then
    args="$args --resume $(cat "$sid")"
  fi
  # Build lineage never resumes: each ticket is a fresh implementation problem
  # and stale build context misleads. Audit and doc lineages do resume.
  # shellcheck disable=SC2086
  timeout "$AGENT_TIMEOUT" "$AGENT_BIN" $args < "$prompt" 2>&1 | tee "$log"
  return "${PIPESTATUS[0]}"        # $? here is tee's, which is always 0
}

# --- gate --------------------------------------------------------------------
# Exit codes lie. Every check matches a summary line, and absence of that line is
# failure. See docs/build-runner.md §7.3.
decolour() { sed -E 's/'"$(printf '\033')"'\[[0-9;]*[a-zA-Z]//g'; }

GATE_SKIPPED=""
gate_skip() { GATE_SKIPPED="${GATE_SKIPPED} $1"; say "${DIM}  skip  $1 — not created yet (M0 builds it)${RESET}"; }

run_gate() {   # run_gate <attempt>
  PHASE="gate"
  local log="$RUNNER_STATE/logs/${TICKET}.gate.$1.log"
  : > "$log"; GATE_SKIPPED=""

  if [ ! -e "api/pyproject.toml" ] && [ ! -e "compose.yaml" ]; then
    gate_skip "format"; gate_skip "lint"; gate_skip "typecheck"; gate_skip "tests"; gate_skip "build"
    say "${DIM}  gate is not built yet — see docs/build-runner.md §7.1${RESET}"
    return 0
  fi

  say "  (gate commands are read from what M0 produced; fill §7.3 of the spec with"
  say "   their real summary lines before trusting a green run)"
  return 0
}

# --- main --------------------------------------------------------------------
main() {
  guard_init || exit 1
  preflight

  if [ "$LIST_ONLY" = "1" ]; then
    head2 "Queue"
    local id st
    for id in $(ticket_ids); do
      st="ready"
      is_done "$id" && st="done"
      ticket_is_blocked "$id" && st="BLOCKED"
      [ "$st" = "ready" ] && { deps_satisfied "$id" || st="waiting on deps"; }
      printf '  %-24s %s\n' "$id" "$st"
    done
    exit 0
  fi

  if guard_stop_requested; then
    die "stop file present — remove $RUNNER_STATE/STOP to continue."
  fi

  TICKET="${TICKET_ARG:-$(next_ticket || true)}"
  [ -n "$TICKET" ] || die "no ticket is ready. Everything is done, blocked, or waiting on dependencies.
       Run: $SELF --list"

  [ -n "$(ticket_file "$TICKET")" ] || die "no such ticket: $TICKET"

  if ticket_is_blocked "$TICKET"; then
    die "$TICKET is marked [BLOCKED]. Building it would guess an answer its owner has not given."
  fi
  if is_done "$TICKET" && [ "$FORCE" != "1" ]; then
    die "$TICKET is already done. Re-run with FORCE=1 to rebuild."
  fi

  MILESTONE="$(printf '%s' "$TICKET" | sed 's/-.*//')"
  local est; est="$(ticket_estimate_hours "$TICKET")"
  [ -n "$est" ] || die "$TICKET has no parseable estimate; the budget guard cannot run."
  guard_budget_allows "$est" || exit 1

  head2 "$TICKET"
  say "  file:      $(ticket_file "$TICKET")"
  say "  estimate:  ${est}h (high end of the range)"
  say "  spent:     $(guard_spent_total)h of ${SPEND_CEILING}h"
  say "  deps:      $(ticket_deps "$TICKET" | tr '\n' ' ')"
  ticket_needs_copy_review "$TICKET" && say "  ${BOLD}copy review required${RESET}"

  mkdir -p "$RUNNER_STATE/prompts" "$RUNNER_STATE/logs" "$MANUAL_TEST_DIR"
  local bp="$RUNNER_STATE/prompts/${TICKET}.build.txt"
  local ap="$RUNNER_STATE/prompts/${TICKET}.audit.txt"
  local dp="$RUNNER_STATE/prompts/${TICKET}.doc.txt"

  PHASE="render"
  render_build_prompt "$TICKET" "$bp"; assert_prompt_intact "$bp" "$TICKET"
  render_audit_prompt "$TICKET" "$ap"; assert_prompt_intact "$ap" "$TICKET"
  render_doc_prompt   "$TICKET" "$dp"; assert_prompt_intact "$dp" "$TICKET"
  say "  prompts:   $bp"

  if [ "$DRY_RUN" = "1" ]; then
    head2 "Dry run — build prompt as rendered"
    cat "$bp"
    head2 "Dry run — nothing was called"
    say "  Read the prompt above in full before trusting it."
    say "  Audit prompt: $ap"
    say "  Doc prompt:   $dp"
    exit 0
  fi

  die "Live runs are not enabled in this build. Gate commands do not exist yet (M0
       creates them), so a live run could not verify anything it produced.
       Use --dry until M0 has landed and docs/build-runner.md §7.3 is filled in."
}

main "$@"
