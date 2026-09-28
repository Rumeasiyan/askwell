#!/bin/sh
# Starts Redis with one user per service (`M8-FIX-SEC-177`, issue #730).
#
# Redis reads passwords from an ACL file, not from the environment, and the
# passwords live in `.env` (C8) like the database's. So this renders
# `users.acl` with the SHA-256 of each password — Redis never sees one in
# plain text — and hands over to the image's own entrypoint, which drops to
# the `redis` user and starts the server exactly as it would have.
#
# Fails loudly rather than starting open: a missing password stops Redis, and
# every service that needs Redis with it. There is no fallback to no
# authentication, because that fallback is the hole this closes.
set -eu

: "${REDIS_API_PASSWORD:?REDIS_API_PASSWORD is not set. Set it in .env (C8); the installer generates it.}"
: "${REDIS_WORKER_PASSWORD:?REDIS_WORKER_PASSWORD is not set. Set it in .env (C8); the installer generates it.}"
: "${REDIS_PROXY_PASSWORD:?REDIS_PROXY_PASSWORD is not set. Set it in .env (C8); the installer generates it.}"

# A `change-me*` value is the placeholder `.env.example` publishes in this
# repository, so it is no more a secret than an empty one (`M9-FIX-SEC-209`,
# issue #750): anything that could read it could authenticate as `api` and
# write a grant the egress proxy honours. The installers replace every
# `change-me*` value; a hand-copied `.env` stops here instead.
placeholders=""
for name in REDIS_API_PASSWORD REDIS_WORKER_PASSWORD REDIS_PROXY_PASSWORD; do
    eval "value=\${$name}"
    case "$value" in
        change-me*) placeholders="$placeholders $name" ;;
    esac
done
if [ -n "$placeholders" ]; then
    echo "Refusing to start: still the public placeholder from .env.example:$placeholders." >&2
    echo "Run the installer, which generates real passwords, or set each to a long random value in .env (C8)." >&2
    exit 1
fi
unset value placeholders

template="$(dirname "$0")/users.acl"
rendered_dir=/tmp/askwell-redis
umask 077
mkdir -p "$rendered_dir"

sha256() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }

# The health check's own password. Fresh every start, never in `.env`, and
# only ever read by the health check inside this container.
healthcheck_password="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
printf '%s' "$healthcheck_password" > "$rendered_dir/healthcheck.pass"

# Comments and blank lines are dropped: the template carries its own
# explanation, and the file Redis loads should be nothing but users.
grep -v -e '^#' -e '^[[:space:]]*$' "$template" | sed \
    -e "s/@HEALTHCHECK_PASSWORD_SHA256@/$(sha256 "$healthcheck_password")/" \
    -e "s/@API_PASSWORD_SHA256@/$(sha256 "$REDIS_API_PASSWORD")/" \
    -e "s/@WORKER_PASSWORD_SHA256@/$(sha256 "$REDIS_WORKER_PASSWORD")/" \
    -e "s/@PROXY_PASSWORD_SHA256@/$(sha256 "$REDIS_PROXY_PASSWORD")/" \
    > "$rendered_dir/users.acl"

if grep -q '@[A-Z_]*_SHA256@' "$rendered_dir/users.acl"; then
    echo "users.acl names a password this script does not fill in. Refusing to start." >&2
    exit 1
fi

chown -R redis:redis "$rendered_dir"

# Nothing past this point needs a password in plain text.
unset REDIS_API_PASSWORD REDIS_WORKER_PASSWORD REDIS_PROXY_PASSWORD healthcheck_password

exec docker-entrypoint.sh "$@"
