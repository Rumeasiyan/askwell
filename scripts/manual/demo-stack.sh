#!/usr/bin/env bash
# The demo stack the manual's screenshots are taken from (docs/manual/AUTHORING.md).
#
#   scripts/manual/demo-stack.sh up     stop the development stack, start a demo one
#   scripts/manual/demo-stack.sh model  recreate the demo API with ASKWELL_MANUAL_MODEL
#   scripts/manual/demo-stack.sh down   remove the demo stack and its data, restart
#                                       the development stack if it was running
#
# The demo stack is a separate Compose project, `askwell-manual`, with its own
# volumes: an empty database, and a demo home folder holding only the fictional
# Meridian Loom documents from eval/fixtures/corpus. Nothing from the
# development database, and nothing of anybody's real files, can appear in a
# screenshot. It reuses the models, the run directory and the native inference
# process already running on this machine (scripts/dev.sh inference).
#
# The two stacks cannot run side by side (the bridge and the databases share
# host ports), so `up` stops the development stack's containers. Its volumes
# are untouched.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE="${ASKWELL_MANUAL_STATE:-$REPO_ROOT/.run/manual-demo}"
PORT="${ASKWELL_MANUAL_PORT:-8010}"
# The demo user's home folder. Short and neutral, because it appears in
# screenshots; a path inside this checkout would show the build machine's.
DEMO_HOME="${ASKWELL_MANUAL_HOME:-/tmp/anna}"
PROJECT=askwell-manual

say() { printf '\033[36m==>\033[0m %s\n' "$*"; }
die() { printf 'demo-stack: %s\n' "$*" >&2; exit 1; }

# What an installed Askwell has, where the development `.env` differs:
# web search is not set up, and the model is the one the demo names.
# ASKWELL_MANUAL_MODEL=missing points at a file that does not exist, which is
# what a fresh install looks like before its download.
MODEL="${ASKWELL_MANUAL_MODEL:-~/.local/share/askwell/models/Qwen_Qwen3.5-4B-Q4_K_M.gguf}"
MODELS_DIR="${ASKWELL_MODELS_DIR:-$HOME/.local/share/askwell/models}"
if [ "$MODEL" = missing ]; then
    # An empty models folder, not just a missing file: the companion models
    # already on this machine would otherwise count as a download half done.
    MODELS_DIR="$STATE/no-models"
    MODEL="~/.local/share/askwell/models/Qwen_Qwen3.5-4B-Q4_K_M.gguf"
    mkdir -p "$MODELS_DIR"
fi

compose_demo() {
    ASKWELL_WEB_SEARCH_PROVIDER="" \
    ASKWELL_INFERENCE_MODEL_PATH="$MODEL" \
    ASKWELL_MODELS_DIR="$MODELS_DIR" \
    ASKWELL_MODELS_DIR_DISPLAY="~/.local/share/askwell/models" \
    ASKWELL_PORT="$PORT" \
    ASKWELL_RUN_DIR="$REPO_ROOT/.run" \
    ASKWELL_ROOTS_MOUNT="$DEMO_HOME" \
    ASKWELL_ROOTS_TARGET="$DEMO_HOME" \
        podman compose -p "$PROJECT" -f "$REPO_ROOT/compose.yaml" "$@"
}

dev_running() {
    [ -n "$(podman ps -q --filter label=com.docker.compose.project=askwell)" ]
}

case "${1:-}" in
    up)
        [ -d "$REPO_ROOT/web/out" ] || die "web/out is missing; run scripts/dev.sh web-build first"
        if dev_running; then
            say "stopping the development stack (its data is kept)"
            touch "$STATE.dev-was-running" 2>/dev/null || { mkdir -p "$(dirname "$STATE")"; touch "$STATE.dev-was-running"; }
            (cd "$REPO_ROOT" && podman compose -p askwell stop >/dev/null)
        fi
        # The development run directory, shared: it is where the native
        # inference supervisor reports its state, and with the development
        # stack stopped nothing else is using its sockets.
        mkdir -p "$STATE" "$DEMO_HOME/Documents"
        rm -rf "$DEMO_HOME/Documents/Meridian Loom"
        cp -r "$REPO_ROOT/eval/fixtures/corpus" "$DEMO_HOME/Documents/Meridian Loom"
        # On an SELinux host the containers may read only what is labelled
        # for them. The demo folder is ours to label; a real home folder is not.
        if command -v chcon >/dev/null && [ "$(getenforce 2>/dev/null)" = Enforcing ]; then
            chcon -R -t container_file_t "$DEMO_HOME"
        fi
        say "starting the demo stack on 127.0.0.1:$PORT"
        compose_demo up -d >/dev/null
        for _ in $(seq 120); do
            if curl -fsS -m 3 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
                say "demo stack is up: http://127.0.0.1:$PORT"
                exit 0
            fi
            sleep 2
        done
        die "the demo stack did not answer /health within four minutes"
        ;;
    model)
        # Recreate whatever reads the model or the models folder; the
        # database volume is kept.
        compose_demo up -d >/dev/null 2>&1
        for _ in $(seq 120); do
            curl -fsS -m 3 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && exit 0
            sleep 2
        done
        die "the demo stack did not come back after the model change"
        ;;
    down)
        say "removing the demo stack and its data"
        compose_demo down -v >/dev/null 2>&1 || true
        rm -rf "$STATE" "$DEMO_HOME"
        if [ -e "$STATE.dev-was-running" ]; then
            rm -f "$STATE.dev-was-running"
            say "restarting the development stack"
            (cd "$REPO_ROOT" && podman compose -p askwell start >/dev/null)
        fi
        ;;
    *)
        die "usage: $0 up|model|down"
        ;;
esac
