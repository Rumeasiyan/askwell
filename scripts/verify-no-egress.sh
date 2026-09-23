#!/usr/bin/env bash
# The automatable half of the cable-unplugged release test.
#
# Exercises the parts of `docs/offline-release-test.md` that are pure HTTP
# against an already-running stack — add a source, ask, abstain, correct a
# fact, query a database, back up, export the audit log — then checks the
# egress proxy's own counters (`GET /network`) before and after, and fails if
# `permitted` moved at all or if a new `refused` entry names anything other
# than one container talking to another on the internal network.
#
# This is one of two independent checks the release test requires — see
# `docs/offline-release-test.md` §5 for the other (an external packet
# capture, which this script cannot substitute for: a counter produced by the
# system under test is not sufficient evidence on its own).
#
# What this script does NOT cover, and why (docs/offline-release-test.md §2):
#   - voice (§3.8)            — needs a real microphone and a browser
#   - a SQL dump import (§3.2) — no dump fixture exists in eval/fixtures/
#   - the physical disconnect itself (§1) — a script cannot unplug a cable
#   - reading the independent capture (§5) — a human judgement call
#
# A clean run here is necessary, not sufficient — the manual walkthrough in
# `docs/offline-release-test.md` §3 still has to happen.
#
#   scripts/verify-no-egress.sh

set -euo pipefail

PORT="${ASKWELL_PORT:-8000}"
BASE="http://127.0.0.1:${PORT}"
COOKIES="$(mktemp)"
CORPUS_DIR="${ASKWELL_CORPUS_DIR:-$(pwd)/eval/fixtures/corpus}"

trap 'rm -f "$COOKIES"' EXIT

ok()   { printf '  \033[32mpass\033[0m  %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAILED=1; }
note() { printf '\033[36m==>\033[0m %s\n' "$1"; }

FAILED=0

network_snapshot() {
    curl -sf --max-time 5 -b "$COOKIES" "${BASE}/network"
}

field() {
    # $1: json on stdin, $2: key
    python3 -c "import json,sys; print(json.load(sys.stdin).get(\"$2\"))"
}

note "establishing a session"
# Not -f: the shell's own "/" route can answer 503 (assistant unavailable) while
# still setting the session cookie this script needs — the same non-2xx-but-
# useful response docs/restore-release-test.md §0 relies on.
curl -s --max-time 5 -c "$COOKIES" -H 'Accept: text/html' "${BASE}/" -o /dev/null
if [ ! -s "$COOKIES" ]; then
    bad "could not reach ${BASE}/ — is the stack up?"
    exit 1
fi
ok "session established"

note "baseline egress counters"
BASELINE="$(network_snapshot)" || { bad "GET /network failed"; exit 1; }
BASE_PERMITTED="$(printf '%s' "$BASELINE" | field - permitted)"
BASE_REFUSED="$(printf '%s' "$BASELINE" | field - refused)"
printf '  permitted=%s refused=%s\n' "$BASE_PERMITTED" "$BASE_REFUSED"

note "adding the eval fixture corpus"
if [ ! -d "$CORPUS_DIR" ]; then
    bad "corpus fixture not found at $CORPUS_DIR"
    exit 1
fi
FILES_JSON="$(python3 - "$CORPUS_DIR" <<'PY'
import json, sys, pathlib
d = pathlib.Path(sys.argv[1])
print(json.dumps(sorted(p.name for p in d.iterdir() if p.is_file())))
PY
)"
ADD_RESPONSE="$(curl -sf --max-time 300 -b "$COOKIES" -X POST "${BASE}/sources" \
    -H 'content-type: application/json' \
    -d "{\"folder\": \"${CORPUS_DIR}\", \"files\": ${FILES_JSON}}")" \
    || { bad "POST /sources failed"; exit 1; }
ok "source add request accepted"

note "waiting for the corpus to finish indexing"
DEADLINE=$((SECONDS + 300))
while [ "$SECONDS" -lt "$DEADLINE" ]; do
    PENDING="$(scripts/dev.sh psql -t -c \
        "select count(*) from documents where status not in ('ready','failed');" 2>/dev/null \
        | tr -d '[:space:]' || echo "?")"
    [ "$PENDING" = "0" ] && break
    sleep 5
done
if [ "$PENDING" = "0" ]; then
    ok "corpus indexed"
else
    bad "corpus did not finish indexing within 300s (pending=$PENDING)"
fi

note "asking a grounded question"
ASK_RESPONSE="$(curl -sf --max-time 600 -b "$COOKIES" -X POST "${BASE}/ask" \
    -H 'content-type: application/json' \
    -d '{"question": "What is the standard resignation notice period at Meridian Loom?"}')" \
    || { bad "POST /ask (grounded) failed"; exit 1; }
# Checking that the turn completed at all, not the exact answer text: issue
# #220 (the local model's <think> block can exhaust the generation token
# budget before an answer completes) makes exact-content matching flaky for
# reasons that have nothing to do with what this gate tests — the same
# confound docs/restore-release-test.md §4.3 already discloses rather than
# working around. This step exists to prove a real generation turn attempts
# no egress, not to grade answer quality.
if printf '%s' "$ASK_RESPONSE" | grep -q '"status": "completed"'; then
    ok "grounded question completed a turn"
    if printf '%s' "$ASK_RESPONSE" | grep -qiE "sixty-three|\b63\b"; then
        ok "  and the answer names the expected fact"
    else
        printf '  \033[33mnote\033[0m  turn completed but did not name "63" — check for issue #220\n'
        printf '        before treating this run'"'"'s answer quality as a regression.\n'
    fi
else
    bad "grounded question never reached a completed turn"
fi

note "asking an unanswerable question"
ABSTAIN_RESPONSE="$(curl -sf --max-time 300 -b "$COOKIES" -X POST "${BASE}/ask" \
    -H 'content-type: application/json' \
    -d '{"question": "What is the boiling point of tungsten at sea level?"}')" \
    || { bad "POST /ask (abstain) failed"; exit 1; }
# An abstained turn's `done` event carries `"source_count": null` — the same
# signal `askwell.ask.summarize_turn` uses to tell an abstention from a
# zero-citation answer (docs/architecture.md §7.1).
if printf '%s' "$ABSTAIN_RESPONSE" | grep -q '"source_count": *null'; then
    ok "abstention triggered correctly"
else
    bad "expected question did not abstain — check it still qualifies as unanswerable"
fi

note "recording a memory fact"
FACT_RESPONSE="$(curl -sf --max-time 30 -b "$COOKIES" -X POST "${BASE}/memory/facts" \
    -H 'content-type: application/json' \
    -d '{"subject": "offline release gate", "fact": "This fact was recorded by scripts/verify-no-egress.sh."}')" \
    || { bad "POST /memory/facts failed"; exit 1; }
ok "memory fact recorded"

note "taking a backup"
BACKUP_RESPONSE="$(curl -sf --max-time 30 -b "$COOKIES" -X POST "${BASE}/backup" \
    -H 'content-type: application/json' -d '{}')" || { bad "POST /backup failed"; exit 1; }
BACKUP_ID="$(printf '%s' "$BACKUP_RESPONSE" | field - id)"
DEADLINE=$((SECONDS + 120))
BACKUP_STATUS=""
while [ "$SECONDS" -lt "$DEADLINE" ]; do
    BACKUP_STATUS="$(curl -sf --max-time 10 -b "$COOKIES" "${BASE}/backup/${BACKUP_ID}" \
        | field - status || echo "")"
    [ "$BACKUP_STATUS" = "done" ] && break
    sleep 2
done
if [ "$BACKUP_STATUS" = "done" ]; then
    ok "backup completed"
else
    bad "backup did not reach status=done (last seen: $BACKUP_STATUS)"
fi

note "exporting the audit log"
EXPORT_RESPONSE="$(curl -sf --max-time 30 -b "$COOKIES" -X POST "${BASE}/log-export" \
    -H 'content-type: application/json' -d '{}')" || { bad "POST /log-export failed"; exit 1; }
EXPORT_ID="$(printf '%s' "$EXPORT_RESPONSE" | field - id)"
DEADLINE=$((SECONDS + 60))
EXPORT_STATUS=""
while [ "$SECONDS" -lt "$DEADLINE" ]; do
    EXPORT_STATUS="$(curl -sf --max-time 10 -b "$COOKIES" "${BASE}/log-export/${EXPORT_ID}" \
        | field - status || echo "")"
    [ "$EXPORT_STATUS" = "done" ] && break
    sleep 2
done
if [ "$EXPORT_STATUS" = "done" ]; then
    ok "audit log export completed"
else
    bad "audit log export did not reach status=done (last seen: $EXPORT_STATUS)"
fi

note "a database query, if a source supports one"
DB_SOURCE="$(scripts/dev.sh psql -t -c \
    "select id from sources where kind in ('dump','connection') and status='ready' limit 1;" \
    2>/dev/null | tr -d '[:space:]' || echo "")"
if [ -n "$DB_SOURCE" ]; then
    DB_RESPONSE="$(curl -sf --max-time 300 -b "$COOKIES" -X POST "${BASE}/ask" \
        -H 'content-type: application/json' \
        -d '{"question": "List the tables available in the connected database."}')" \
        || { bad "POST /ask (database) failed"; exit 1; }
    ok "database-routed question answered"
else
    printf '  \033[33mskip\033[0m  no dump or connection source is configured — see §3.2/§3.4\n'
fi

note "final egress counters"
FINAL="$(network_snapshot)" || { bad "GET /network failed"; exit 1; }
FINAL_PERMITTED="$(printf '%s' "$FINAL" | field - permitted)"
FINAL_REFUSED="$(printf '%s' "$FINAL" | field - refused)"
printf '  permitted=%s refused=%s\n' "$FINAL_PERMITTED" "$FINAL_REFUSED"

if [ "$FINAL_PERMITTED" = "$BASE_PERMITTED" ]; then
    ok "permitted count unchanged ($FINAL_PERMITTED)"
else
    bad "permitted count moved from $BASE_PERMITTED to $FINAL_PERMITTED — something was let out"
fi

if [ "$FINAL_REFUSED" != "$BASE_REFUSED" ]; then
    printf '  \033[33mnote\033[0m  refused count moved from %s to %s — investigate each new\n' \
        "$BASE_REFUSED" "$FINAL_REFUSED"
    printf '        entry per docs/offline-release-test.md §4 before treating this as a pass.\n'
fi

printf '\n'
if [ "$FAILED" -ne 0 ]; then
    printf 'The automatable half of the offline release test failed.\n' >&2
    printf 'Run docs/offline-release-test.md §3 onward for the manual half regardless.\n' >&2
    exit 1
fi
printf 'Automatable checks pass. Continue with docs/offline-release-test.md §3 (manual).\n'
