#!/usr/bin/env bash
# The automatable half of the online-mode release test (`M8-ONLINE-TEST-176`).
#
# Exercises the parts of `docs/online-release-test.md` that are HTTP against an
# already-running stack with a provider key already stored (Settings → Online
# AI, the walkthrough's own step), and checks the egress proxy's counters
# (`GET /network`) before and after:
#
#   1. two conversations; online AI switched on for one of them;
#   2. while it is on, a dependency in the api and in the worker container asks
#      the proxy for the authorised destination with no credential — refused;
#   3. the sandbox has no route to the proxy, to the destination, or to a name;
#   4. the online conversation asks a question — counted once, against that
#      conversation and that destination (BLOCKED while #737 refuses every
#      online send);
#   5. the local conversation asks a question — nothing is counted;
#   6. online AI is switched off — the authorisation is gone at once, and the
#      next question in that conversation is counted nowhere.
#
# Exits 0 when every check passes, 1 when any fails, and 2 when nothing failed
# but a check could not run (step 4 while #737 is open). 2 is `BLOCKED` in
# `docs/release-checklist.md`, never a pass.
#
# This is one of two independent checks. The other is the packet capture in
# `docs/online-release-test.md` §2 and §6: a counter produced by the system
# under test is not sufficient evidence on its own. What this script cannot do,
# and why (docs/online-release-test.md §3):
#   - read the capture — a human judgement, against the one address allowed;
#   - present a conversation's credential itself — it lives only in the API
#     process's memory (`M8-ONLINE-SEC-169`), which is the point of it. The
#     name-versus-address and retry-storm edge cases are therefore pinned by
#     `api/tests/test_egress.py`, `api/tests/test_inference_provider.py` and
#     `api/tests/test_ask_online.py`, and re-checked in the capture.
#
#   scripts/verify-online-egress.sh

set -euo pipefail

PORT="${ASKWELL_PORT:-8000}"
BASE="http://127.0.0.1:${PORT}"
PROXY_HOST="egress-proxy"
PROXY_PORT="3128"
COOKIES="$(mktemp)"

trap 'rm -f "$COOKIES"' EXIT

ok()      { printf '  \033[32mpass\033[0m  %s\n' "$1"; }
bad()     { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAILED=1; }
blocked() { printf '  \033[33mBLOCKED\033[0m  %s\n' "$1"; BLOCKED=1; }
note()    { printf '\033[36m==>\033[0m %s\n' "$1"; }

FAILED=0
BLOCKED=0

# `podman compose` announces its external provider on stderr; only stdout is read.
in_service() {
    local service="$1"
    shift
    podman compose exec -T "$service" "$@" 2>/dev/null
}

json() {
    # $1: python expression over `d`, the JSON document on stdin
    python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"
}

network() {
    curl -sf --max-time 5 -b "$COOKIES" "${BASE}/network"
}

# The first line of the proxy's answer to a CONNECT sent from inside a
# container, with no credential: what any dependency honouring HTTPS_PROXY does.
connect_from() {
    local service="$1" destination="$2"
    in_service "$service" python -c "
import socket, sys
try:
    s = socket.create_connection(('${PROXY_HOST}', ${PROXY_PORT}), timeout=5)
    s.sendall(b'CONNECT ${destination} HTTP/1.1\r\nHost: ${destination}\r\n\r\n')
    print(s.recv(256).split(b'\r\n')[0].decode('latin-1'))
except OSError as error:
    print(f'no connection: {error}')
" || echo "exec failed"
}

ask() {
    # $1: conversation id, $2: question. Prints the HTTP status, then the body.
    curl -s --max-time 600 -b "$COOKIES" -X POST "${BASE}/ask" \
        -H 'content-type: application/json' \
        -d "{\"question\": \"$2\", \"conversation_id\": \"$1\"}" \
        -w '\n%{http_code}'
}

permitted_for() {
    # $1: /network JSON, $2: conversation id → that conversation's permitted count
    printf '%s' "$1" | json "sum(i['permitted'] for i in d['permitted_by_conversation'] if i['conversation_id'] == '$2')"
}

note "establishing a session"
curl -s --max-time 5 -c "$COOKIES" -H 'Accept: text/html' "${BASE}/" -o /dev/null
if [ ! -s "$COOKIES" ]; then
    bad "could not reach ${BASE}/ — is the stack up?"
    exit 1
fi
ok "session established"

note "the stored provider key"
KEY_STATUS="$(curl -sf --max-time 5 -b "$COOKIES" "${BASE}/settings/online-key")" \
    || { bad "GET /settings/online-key failed"; exit 1; }
if [ "$(printf '%s' "$KEY_STATUS" | json "d['set'] and d['available']")" != "True" ]; then
    bad "no usable provider key: $(printf '%s' "$KEY_STATUS" | json "d['unavailable_reason']")"
    printf '        Store one in Settings → Online AI first (docs/online-release-test.md §4.1).\n'
    exit 1
fi
DESTINATION="$(printf '%s' "$KEY_STATUS" | json "d['provider']['destination']")"
DEST_HOST="${DESTINATION%:*}"
DEST_PORT="${DESTINATION##*:}"
ok "key held for ${DESTINATION}"

note "baseline egress counters"
BASELINE="$(network)" || { bad "GET /network failed"; exit 1; }
if [ "$(printf '%s' "$BASELINE" | json "d['available']")" != "True" ]; then
    bad "the proxy's counters are unavailable — the run has no baseline"
    exit 1
fi
BASE_PERMITTED="$(printf '%s' "$BASELINE" | json "d['permitted']")"
BASE_REFUSED="$(printf '%s' "$BASELINE" | json "d['refused']")"
if [ "$(printf '%s' "$BASELINE" | json "len(d['authorised'])")" != "0" ]; then
    bad "a conversation is already authorised before the run: switch it off and start again"
    exit 1
fi
printf '  permitted=%s refused=%s\n' "$BASE_PERMITTED" "$BASE_REFUSED"

note "two conversations, one switched online"
ONLINE_ID="$(curl -sf --max-time 10 -b "$COOKIES" -X POST "${BASE}/conversations" | json "d['conversation_id']")"
LOCAL_ID="$(curl -sf --max-time 10 -b "$COOKIES" -X POST "${BASE}/conversations" | json "d['conversation_id']")"
ENABLED="$(curl -s --max-time 10 -b "$COOKIES" -X POST "${BASE}/conversations/${ONLINE_ID}/online")"
if [ "$(printf '%s' "$ENABLED" | json "d.get('ai_backend')")" != "online" ]; then
    bad "could not switch ${ONLINE_ID} online: ${ENABLED}"
    exit 1
fi
# Once #737 records the wording, a send also needs it confirmed for this
# conversation — the step a person takes in the interface. Until then there is
# nothing to confirm, and step 4 reports BLOCKED.
DISCLOSURE_VERSION="$(printf '%s' "$ENABLED" | json "d['disclosure']['version'] or ''")"
if [ -n "$DISCLOSURE_VERSION" ]; then
    CONFIRMED="$(curl -s --max-time 10 -b "$COOKIES" -X POST \
        "${BASE}/conversations/${ONLINE_ID}/online/disclosure" \
        -H 'content-type: application/json' -d "{\"version\": \"${DISCLOSURE_VERSION}\"}")"
    if [ "$(printf '%s' "$CONFIRMED" | json "d.get('send_permitted')")" != "True" ]; then
        bad "could not confirm disclosure ${DISCLOSURE_VERSION} for ${ONLINE_ID}: ${CONFIRMED}"
    fi
fi
printf '  online=%s local=%s\n' "$ONLINE_ID" "$LOCAL_ID"
AUTHORISED="$(network | json "[(a['conversation_id'], a['destination']) for a in d['authorised']]")"
if [ "$AUTHORISED" = "[('${ONLINE_ID}', '${DESTINATION}')]" ]; then
    ok "the proxy holds exactly one authorisation: that conversation, that destination"
else
    bad "the proxy's authorisations are not exactly the one enabled: ${AUTHORISED}"
fi

note "a dependency asking for the authorised destination while it is authorised"
PROBES=0
for service in api worker; do
    ANSWER="$(connect_from "$service" "$DESTINATION")"
    PROBES=$((PROBES + 1))
    if printf '%s' "$ANSWER" | grep -q ' 403 '; then
        ok "${service}: refused (${ANSWER})"
    else
        bad "${service}: expected 403 from the proxy, got: ${ANSWER}"
    fi
done

note "a dependency ignoring the proxy"
# Resolved where the proxy resolves it: nothing else on the stack can.
DEST_ADDRESS="$(in_service "$PROXY_HOST" python -c "
import socket
print(socket.getaddrinfo('${DEST_HOST}', ${DEST_PORT}, type=socket.SOCK_STREAM)[0][4][0])
" || true)"
for target in "$DEST_HOST" ${DEST_ADDRESS:+"$DEST_ADDRESS"}; do
    DIRECT="$(in_service api python -c "
import socket
try:
    socket.create_connection(('${target}', ${DEST_PORT}), timeout=5)
    print('CONNECTED')
except OSError as error:
    print(f'no route: {error}')
" || echo "exec failed")"
    if printf '%s' "$DIRECT" | grep -q '^no route'; then
        ok "api → ${target}:${DEST_PORT}: ${DIRECT}"
    else
        bad "api reached ${target}:${DEST_PORT} without the proxy: ${DIRECT}"
    fi
done

note "the sandbox, while a conversation is online"
for target in "${PROXY_HOST}/${PROXY_PORT}" "${DEST_HOST}/${DEST_PORT}" ${DEST_ADDRESS:+"${DEST_ADDRESS}/${DEST_PORT}"}; do
    if in_service sandbox bash -c "timeout 5 bash -c '</dev/tcp/${target}'" >/dev/null 2>&1; then
        bad "sandbox reached ${target}"
    else
        ok "sandbox: no route to ${target}"
    fi
done
if in_service sandbox getent hosts "$DEST_HOST" >/dev/null 2>&1; then
    bad "sandbox resolved ${DEST_HOST}"
else
    ok "sandbox: ${DEST_HOST} does not resolve"
fi

note "the online conversation asks"
ONLINE_SENDS=0
RESPONSE="$(ask "$ONLINE_ID" "What is the standard resignation notice period at Meridian Loom?")"
STATUS="${RESPONSE##*$'\n'}"
# Only #737's refusal is BLOCKED. The other 409, a disclosure not confirmed for
# this conversation, is a run that was not set up, and reads as a failure.
if [ "$STATUS" = "409" ] && printf '%s' "$RESPONSE" | grep -q 'has not been decided yet'; then
    blocked "online sends are refused: ${RESPONSE%$'\n'*} (#737). The positive half cannot run."
elif [ "$STATUS" = "200" ]; then
    ONLINE_SENDS=1
    AFTER="$(network)"
    if [ "$(permitted_for "$AFTER" "$ONLINE_ID")" = "1" ]; then
        ok "one permitted connection, attributed to ${ONLINE_ID} → ${DESTINATION}"
    else
        bad "expected exactly one permitted connection for ${ONLINE_ID}: $(printf '%s' "$AFTER" | json "d['permitted_by_conversation']")"
    fi
else
    bad "POST /ask in the online conversation answered ${STATUS}"
fi

note "the local conversation asks, in the same session"
BEFORE_LOCAL="$(network | json "d['permitted']")"
RESPONSE="$(ask "$LOCAL_ID" "What is the standard resignation notice period at Meridian Loom?")"
STATUS="${RESPONSE##*$'\n'}"
AFTER_LOCAL="$(network)"
if [ "$STATUS" != "200" ]; then
    bad "POST /ask in the local conversation answered ${STATUS}"
elif [ "$(printf '%s' "$AFTER_LOCAL" | json "d['permitted']")" = "$BEFORE_LOCAL" ] \
    && [ "$(permitted_for "$AFTER_LOCAL" "$LOCAL_ID")" = "0" ]; then
    ok "nothing permitted for the local conversation"
else
    bad "the local conversation's question moved the permitted count"
fi

note "switching online AI off"
OFF="$(curl -sf --max-time 10 -b "$COOKIES" -X DELETE "${BASE}/conversations/${ONLINE_ID}/online")" \
    || { bad "DELETE /conversations/${ONLINE_ID}/online failed"; OFF='{}'; }
AFTER_OFF="$(network)"
if [ "$(printf '%s' "$OFF" | json "d.get('ai_backend')")" = "local" ] \
    && [ "$(printf '%s' "$AFTER_OFF" | json "len(d['authorised'])")" = "0" ]; then
    ok "the authorisation is gone as soon as the request returns"
else
    bad "the authorisation outlived switching it off: $(printf '%s' "$AFTER_OFF" | json "d['authorised']")"
fi
BEFORE_AFTER="$(printf '%s' "$AFTER_OFF" | json "d['permitted']")"
RESPONSE="$(ask "$ONLINE_ID" "What is the standard resignation notice period at Meridian Loom?")"
STATUS="${RESPONSE##*$'\n'}"
if [ "$STATUS" = "200" ] && [ "$(network | json "d['permitted']")" = "$BEFORE_AFTER" ]; then
    ok "the next question in that conversation is answered with nothing permitted"
else
    bad "after switching off: status ${STATUS}, permitted ${BEFORE_AFTER} → $(network | json "d['permitted']")"
fi

note "final egress counters"
FINAL="$(network)" || { bad "GET /network failed"; exit 1; }
FINAL_PERMITTED="$(printf '%s' "$FINAL" | json "d['permitted']")"
FINAL_REFUSED="$(printf '%s' "$FINAL" | json "d['refused']")"
printf '  permitted=%s refused=%s\n' "$FINAL_PERMITTED" "$FINAL_REFUSED"

if [ "$FINAL_PERMITTED" -eq $((BASE_PERMITTED + ONLINE_SENDS)) ]; then
    ok "permitted moved by exactly the online sends (${ONLINE_SENDS})"
else
    bad "permitted moved from ${BASE_PERMITTED} to ${FINAL_PERMITTED}; only ${ONLINE_SENDS} online send(s) were made"
fi
if [ "$FINAL_REFUSED" -eq $((BASE_REFUSED + PROBES)) ]; then
    ok "refused moved by exactly this script's own probes (${PROBES})"
else
    bad "refused moved from ${BASE_REFUSED} to ${FINAL_REFUSED}; this script made ${PROBES} — investigate every other one (docs/online-release-test.md §5)"
fi

printf '\n'
if [ "$FAILED" -ne 0 ]; then
    printf 'The automatable half of the online-mode release test FAILED.\n' >&2
    exit 1
fi
if [ "$BLOCKED" -ne 0 ]; then
    printf 'Nothing failed, but the online send could not run: BLOCKED, not a pass.\n' >&2
    exit 2
fi
printf 'Automatable checks pass. Read the capture: docs/online-release-test.md §6.\n'
