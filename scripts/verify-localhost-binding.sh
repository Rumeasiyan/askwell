#!/usr/bin/env bash
# Prove that Askwell is not reachable from the network.
#
# `"8000:8000"` and `"127.0.0.1:8000:8000"` differ by nine characters and
# produce the same working product on the developer's machine. The first one
# puts the user's entire corpus on whatever network they are on. Nothing about
# that difference is visible from inside Askwell, which is why this check comes
# from outside it.
#
# Part of the release checklist. A binding to all interfaces fails it.
#
#   scripts/verify-localhost-binding.sh

set -euo pipefail

SELF="scripts/verify-localhost-binding.sh"
CONTAINER="${ASKWELL_CONTAINER:-podman}"
PORT="${ASKWELL_PORT:-8000}"
PROBE_IMAGE="${ASKWELL_PROBE_IMAGE:-docker.io/library/alpine:3.20}"

ok()   { printf '  \033[32mpass\033[0m  %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAILED=1; }
note() { printf '\033[36m==>\033[0m %s\n' "$1"; }

FAILED=0

note "the API answers on loopback"
if curl -sf --max-time 5 "http://127.0.0.1:${PORT}/health" >/dev/null; then
    ok "http://127.0.0.1:${PORT}/health"
else
    bad "the API is not answering on loopback — is the stack up?"
fi

note "what the port is bound to"
BINDINGS="$(ss -tln 2>/dev/null | awk -v p=":${PORT}" '$4 ~ p {print $4}' || true)"
if [ -z "$BINDINGS" ]; then
    bad "nothing is listening on port ${PORT}"
else
    while read -r binding; do
        case "$binding" in
            127.0.0.1:*|\[::1\]:*) ok "bound to $binding" ;;
            0.0.0.0:*|\[::\]:*|\*:*)
                bad "bound to $binding — this is every interface on the machine" ;;
            *) bad "bound to $binding, which is not loopback" ;;
        esac
    done <<< "$BINDINGS"
fi

note "no other service is published"
PUBLISHED="$("$CONTAINER" ps --format '{{.Names}} {{.Ports}}' 2>/dev/null | grep -v '^\s*$' || true)"
while read -r line; do
    [ -n "$line" ] || continue
    name="${line%% *}"
    ports="${line#* }"
    case "$name" in askwell-*) ;; *) continue ;; esac
    # Only an entry containing `->` is published to the host. A bare
    # `5432/tcp` is an EXPOSE in the image — documentation of what the
    # container listens on internally, with no host binding at all. Treating
    # those as failures makes the check fail always, and a check that always
    # fails is a check nobody runs.
    published="$(printf '%s' "$ports" | tr ',' '\n' | grep -- '->' || true)"

    if [ -z "$published" ]; then
        ok "$name publishes nothing to the host"
        continue
    fi

    while read -r mapping; do
        [ -n "$mapping" ] || continue
        mapping="$(printf '%s' "$mapping" | tr -d ' ')"
        case "$mapping" in
            127.0.0.1:*|\[::1\]:*) ok "$name publishes $mapping" ;;
            *) bad "$name publishes $mapping to a non-loopback address" ;;
        esac
    done <<< "$published"
done <<< "$PUBLISHED"

# Corroboration, not the primary check — and this order matters.
#
# A container has its own network namespace, so reaching the host by one of its
# addresses is close to the path a colleague's laptop would take. But it is not
# the same path: whether a rootless container can route to a given host address
# depends on the container network, the host firewall and the interface. This
# was measured, not assumed — with the API deliberately bound to every
# interface, this probe found it reachable on the machine's Tailscale address
# and *refused* on its LAN address. A check that relies on this alone would
# have passed a machine with no Tailscale.
#
# So `ss` above is what decides, and this is what catches the case where `ss`
# looks right and something else republishes the port anyway.
note "reaching the machine by its own network addresses, from outside its namespace"
ADDRESSES="$(ip -4 -o addr show scope global 2>/dev/null | awk '{split($4,a,"/"); print a[1]}' || true)"
if [ -z "$ADDRESSES" ]; then
    printf '  \033[33mskip\033[0m  this machine has no non-loopback address to try\n'
else
    while read -r address; do
        [ -n "$address" ] || continue
        if "$CONTAINER" run --rm "$PROBE_IMAGE" \
            timeout 5 nc -z -w 3 "$address" "$PORT" >/dev/null 2>&1; then
            bad "reachable at ${address}:${PORT} from another network namespace"
        else
            ok "refused at ${address}:${PORT}"
        fi
    done <<< "$ADDRESSES"
fi

printf '\n'
if [ "$FAILED" -ne 0 ]; then
    printf 'Askwell is reachable from the network. This fails the release checklist:\n'
    printf 'the user'"'"'s entire corpus is on the other side of that port.\n' >&2
    exit 1
fi
printf 'Askwell answers on loopback and nowhere else.\n'
