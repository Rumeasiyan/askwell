#!/usr/bin/env bash
# Run the Python toolchain inside the API image, against the working tree.
#
# The host needs Podman and nothing else. The development machine runs Python
# 3.14; the project targets 3.12 and its dependencies have no 3.14 wheels, so
# the host interpreter is never invoked — see AGENTS.md §5.
#
#   scripts/dev.sh lint        ruff check
#   scripts/dev.sh format      ruff format (writes)
#   scripts/dev.sh fmt-check   ruff format --check (writes nothing; what CI runs)
#   scripts/dev.sh typecheck   mypy --strict
#   scripts/dev.sh test        pytest
#   scripts/dev.sh check       all of the above, read-only, in order
#   scripts/dev.sh lock        regenerate api/uv.lock deliberately
#
#   scripts/dev.sh web-install  install frontend dependencies (needs the network)
#   scripts/dev.sh web-build    build the frontend to web/out
#   scripts/dev.sh web-check    typecheck, lint, build, contrast, offline scan
#   scripts/dev.sh web-run ...  any command inside the frontend image
#
#   scripts/dev.sh db <args>    alembic against the running stack
#                               (e.g. `db upgrade head`, `db revision --autogenerate -m "..."`)
#   scripts/dev.sh psql         a psql shell on the stack's database
#   scripts/dev.sh inference    the native inference supervisor, ON THE HOST
#   scripts/dev.sh test-db      the database-backed tests, against the stack
#   scripts/dev.sh build       rebuild both images (build-api / build-web for one)
#   scripts/dev.sh shell       an interactive shell in the image
#   scripts/dev.sh run ...     any command inside the image

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${ASKWELL_API_IMAGE:-localhost/askwell-api:dev}"
WEB_IMAGE="${ASKWELL_WEB_IMAGE:-localhost/askwell-web:dev}"
SELF="scripts/dev.sh"

die() { printf '%s: %s\n' "$SELF" "$*" >&2; exit 1; }

# Podman warns on --tty with no terminal, and the warning looks like an error
# in CI logs. Ask instead of assuming.
TTY_FLAGS=()
[ -t 0 ] && TTY_FLAGS=(-it)
note() { printf '\033[36m==>\033[0m %s\n' "$*" >&2; }

# Podman locally; CI runners carry Docker and not always Podman. Same images,
# same commands — the runtime is the one thing allowed to differ, because a CI
# run that cannot use the project's own entry point ends up reimplementing it
# and then drifting from it.
CONTAINER="${ASKWELL_CONTAINER:-}"
if [ -z "$CONTAINER" ]; then
    if command -v podman >/dev/null 2>&1; then
        CONTAINER=podman
    elif command -v docker >/dev/null 2>&1; then
        CONTAINER=docker
    else
        die "neither podman nor docker is installed. One of them is the only thing this project needs on the host."
    fi
fi

# Read from the environment first, then .env, then the fallback. A second
# hardcoded copy of the credentials is how one of them ends up committed; the
# environment comes first so CI can supply them without writing a .env file it
# would then have to clean up.
_env_value() {
    local name="$1" fallback="$2"
    local found="${!name:-}"
    if [ -z "$found" ]; then
        found="$(grep -E "^${name}=" "$REPO_ROOT/.env" 2>/dev/null | tail -1 | cut -d= -f2-)"
    fi
    printf '%s' "${found:-$fallback}"
}
_db_user() { _env_value POSTGRES_USER askwell; }
# `postgres` is the Compose service name. CI reaches a service container on
# loopback instead, and overrides this.
_db_host() { _env_value ASKWELL_DB_HOST postgres; }
_db_name() { _env_value POSTGRES_DB askwell; }
_app_password() {
    local value
    value="$(_env_value POSTGRES_APP_PASSWORD "")"
    [ -n "$value" ] || die "POSTGRES_APP_PASSWORD is not set in .env. Copy .env.example and set it."
    printf '%s' "$value"
}
_db_password() {
    local value
    value="$(_env_value POSTGRES_PASSWORD "")"
    [ -n "$value" ] || die "POSTGRES_PASSWORD is not set in .env. Copy .env.example and set it."
    printf '%s' "$value"
}

build_image() {
    note "building $IMAGE"
    # Context is the repository root: the version comes from root VERSION.
    "$CONTAINER" build -f "$REPO_ROOT/api/Dockerfile" -t "$IMAGE" "$REPO_ROOT"
}

# `podman image exists` has no docker equivalent; `image inspect` works on both.
_image_exists() { "$CONTAINER" image inspect "$1" >/dev/null 2>&1; }

image_exists() { _image_exists "$IMAGE"; }

build_web_image() {
    note "building $WEB_IMAGE"
    "$CONTAINER" build -f "$REPO_ROOT/web/Dockerfile" -t "$WEB_IMAGE" "$REPO_ROOT"
}

# Same shape as in_image, for the Node toolchain. Frontend commands run with
# no network for the same reason the Python ones do: `install` is the only
# step that has any business reaching a registry.
in_web() {
    _image_exists "$WEB_IMAGE" || { note "$WEB_IMAGE not built yet"; build_web_image; }
    "$CONTAINER" run --rm \
        --network=none \
        -v "$REPO_ROOT":/app:z \
        -w /app/web \
        "$@"
}

in_web_networked() {
    _image_exists "$WEB_IMAGE" || { note "$WEB_IMAGE not built yet"; build_web_image; }
    "$CONTAINER" run --rm \
        -v "$REPO_ROOT":/app:z \
        -w /app/web \
        "$@"
}

# :z, not :Z. Both relabel for SELinux, which this machine enforces — without
# either, the container reads nothing and the error does not mention SELinux.
# :Z applies a *private* label, so two containers sharing this directory
# relabel it out from under each other; two test runs at once then fail with a
# permission error that has nothing to do with either test.
in_image() {
    image_exists || { note "$IMAGE not built yet"; build_image; }
    "$CONTAINER" run --rm \
        --network=none \
        -v "$REPO_ROOT":/app:z \
        -w /app/api \
        -e PYTHONDONTWRITEBYTECODE=1 \
        "$@"
}

# C1: the toolchain has no business reaching the network once the image exists.
# --network=none above is not a precaution, it is the constraint being enforced
# where it is cheapest to enforce. `lock` is the one command that legitimately
# resolves from an index, and it opts back in explicitly.
in_image_networked() {
    image_exists || { note "$IMAGE not built yet"; build_image; }
    "$CONTAINER" run --rm \
        -v "$REPO_ROOT":/app:z \
        -w /app/api \
        "$@"
}

cmd="${1:-check}"
shift || true

case "$cmd" in
    lint)      in_image "${TTY_FLAGS[@]}" "$IMAGE" ruff check "$@" ;;
    format)    in_image "${TTY_FLAGS[@]}" "$IMAGE" ruff format "$@" ;;
    fmt-check) in_image "${TTY_FLAGS[@]}" "$IMAGE" ruff format --check "$@" ;;
    typecheck) in_image "${TTY_FLAGS[@]}" "$IMAGE" mypy "$@" ;;
    test)      in_image "${TTY_FLAGS[@]}" "$IMAGE" pytest "$@" ;;

    check)
        # Ordered cheapest-first so the fastest signal arrives first.
        note "lint";      in_image "$IMAGE" ruff check
        note "format";    in_image "$IMAGE" ruff format --check
        note "typecheck"; in_image "$IMAGE" mypy
        note "test";      in_image "$IMAGE" pytest
        note "all checks passed"
        ;;

    lock)
        note "resolving dependencies from the index — this is the one command that may"
        in_image_networked "${TTY_FLAGS[@]}" "$IMAGE" uv lock --upgrade "$@"
        note "api/uv.lock rewritten. Review the diff before committing it."
        ;;

    web-install)
        note "installing frontend dependencies from the registry — this is the one"
        note "frontend command that may reach the network"
        in_web_networked "${TTY_FLAGS[@]}" "$WEB_IMAGE" pnpm install "$@"
        ;;

    web-build)  in_web "${TTY_FLAGS[@]}" "$WEB_IMAGE" pnpm build "$@" ;;

    web-check)
        note "typecheck";  in_web "$WEB_IMAGE" pnpm typecheck
        note "lint";       in_web "$WEB_IMAGE" pnpm lint
        note "build";      in_web "$WEB_IMAGE" pnpm build
        # Both of these are constraints, not preferences. Contrast failures are
        # invisible to whoever is not affected by them; an external URL breaks
        # C1 on a machine with no network, which is the machine this product is
        # for.
        note "version discipline";     in_web "$WEB_IMAGE" pnpm check-version
        note "token hygiene";          in_web "$WEB_IMAGE" pnpm check-tokens
        note "contrast (both themes)"; in_web "$WEB_IMAGE" pnpm contrast
        note "no external hosts";      in_web "$WEB_IMAGE" pnpm check-offline
        note "frontend checks passed"
        ;;

    web-run)
        [ "$#" -gt 0 ] || die "web-run needs a command, e.g. $SELF web-run pnpm why react"
        in_web "${TTY_FLAGS[@]}" "$WEB_IMAGE" "$@"
        ;;

    web-shell) in_web "${TTY_FLAGS[@]}" "$WEB_IMAGE" bash ;;

    db)
        [ -n "${ASKWELL_ENV_FILE:-}" ] || [ ! -f "$REPO_ROOT/.env" ] || ASKWELL_ENV_FILE="$REPO_ROOT/.env"
        # Alembic needs three things at once that no other command needs
        # together: the repository mounted so a generated migration lands in the
        # working tree rather than inside a container, the stack's network so it
        # can reach Postgres, and the database URL. Hence its own entry point
        # rather than `run`, which is deliberately network-less.
        [ "$#" -gt 0 ] || die "db needs an alembic command, e.g. $SELF db upgrade head"
        _image_exists "$IMAGE" || build_image
        "$CONTAINER" run --rm "${TTY_FLAGS[@]}" \
            --network "${ASKWELL_COMPOSE_NETWORK:-askwell_default}" \
            ${ASKWELL_ENV_FILE:+--env-file "$ASKWELL_ENV_FILE"} \
            -e ASKWELL_DATABASE_URL="postgresql://$(_db_user):$(_db_password)@$(_db_host):5432/$(_db_name)" \
            -v "$REPO_ROOT":/app:z \
            -w /app/api \
            "$IMAGE" alembic "$@"
        ;;

    test-db)
        # These assert what the database refuses, so they need a real one. They
        # are deselected from `test` because that runs with no network; here
        # they are selected explicitly and fail — rather than skip — if the
        # database is not there.
        #
        # TEST_DATABASE_URL names the server, not the database to use: the
        # harness creates its own for the run and drops it afterwards, so a run
        # never touches the development data and two runs cannot collide.
        _image_exists "$IMAGE" || build_image
        "$CONTAINER" run --rm "${TTY_FLAGS[@]}" \
            --network "${ASKWELL_COMPOSE_NETWORK:-askwell_default}" \
            -e TEST_DATABASE_URL="postgresql://$(_db_user):$(_db_password)@$(_db_host):5432/$(_db_name)" \
            -e TEST_APP_PASSWORD="$(_app_password)" \
            -v "$REPO_ROOT":/app:z \
            -w /app/api \
            "$IMAGE" pytest -m requires_db "$@"
        ;;

    inference)
        # The one command that does not run in a container, and cannot. GPU
        # acceleration only works from the host; a containerised API cannot
        # start a host process; and the host's Python is not ours to choose —
        # this machine runs 3.14 and the package pins 3.12. So the supervisor
        # is a standalone stdlib-only script. See docs/decisions.md.
        binary="$(_env_value ASKWELL_INFERENCE_BINARY llama-server)"
        command -v "$binary" >/dev/null 2>&1 || die \
            "$binary is not on PATH. Askwell runs llama.cpp natively so that GPU acceleration works; it is not in the container images."
        command -v python3 >/dev/null 2>&1 || die "python3 is needed on the host to supervise inference"

        mkdir -p "$REPO_ROOT/.run"
        note "inference supervisor, on the host (not a container)"
        note "socket: $REPO_ROOT/.run/inference.sock"

        set -a
        # shellcheck disable=SC1091
        [ -f "$REPO_ROOT/.env" ] && . "$REPO_ROOT/.env"
        set +a
        ASKWELL_INFERENCE_SOCKET="$REPO_ROOT/.run/inference.sock" \
            exec python3 "$REPO_ROOT/deploy/inference/askwell-inference" "$@"
        ;;

    psql)
        "$CONTAINER" compose exec "${TTY_FLAGS[@]}" postgres \
            psql -U "$(_db_user)" -d "$(_db_name)" "$@"
        ;;

    build)     build_image; build_web_image ;;
    build-api) build_image ;;
    build-web) build_web_image ;;
    shell) in_image "${TTY_FLAGS[@]}" "$IMAGE" bash ;;
    run)
        [ "$#" -gt 0 ] || die "run needs a command, e.g. $SELF run python -c 'import askwell'"
        in_image "${TTY_FLAGS[@]}" "$IMAGE" "$@"
        ;;

    -h|--help|help)
        sed -n '2,26p' "$REPO_ROOT/$SELF" | sed 's/^# \{0,1\}//'
        ;;

    *) die "unknown command '$cmd'. Try: $SELF --help" ;;
esac
