# Askwell frontend toolchain image.
#
# Same reasoning as api/Dockerfile: the host needs Podman and nothing else.
# This machine happens to carry a usable Node, but relying on that makes the
# claim in AGENTS.md §5 false for the next contributor, whose Node will be a
# different major version on a different libc.
#
# Build context is the REPOSITORY ROOT (the version comes from root VERSION):
#   podman build -f web/Dockerfile -t askwell-web .

FROM docker.io/library/node:22-bookworm-slim

# Fail loudly rather than drift. Next 16 and React 19 both want a modern Node,
# and a silent major bump here surfaces as a build error with no obvious cause.
RUN set -eu; \
    actual="$(node -p 'process.versions.node.split(".")[0]')"; \
    if [ "$actual" != "22" ]; then \
        echo "FATAL: this image must be Node 22, found ${actual}." >&2; \
        exit 1; \
    fi; \
    echo "Node $(node -v) confirmed."

# pnpm through corepack. `web/package.json`'s `packageManager` field is the
# pin; this bakes that exact version into the image so corepack never reaches
# the registry at build time. Without it, a build with no network dies in
# corepack — `getaddrinfo EAI_AGAIN registry.npmjs.org` — long before any of
# the project's own code runs, which is a confusing way to discover C1.
#
# The version here must match `packageManager` in web/package.json. It is
# checked below rather than trusted.
#
# COREPACK_HOME is set explicitly and before the prepare. Corepack caches
# prepared package managers under $HOME by default, and HOME is changed below
# so that Next has somewhere writable — which would leave the baked pnpm in a
# directory nothing looks in any more, and the offline build back to fetching
# it. A cache keyed on a variable that later changes is not a cache.
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    COREPACK_ENABLE_AUTO_PIN=0 \
    COREPACK_HOME=/opt/corepack
RUN corepack enable && corepack prepare pnpm@11.24.0 --activate

COPY web/package.json /tmp/package.json
RUN set -eu; \
    pinned="$(node -p "require('/tmp/package.json').packageManager")"; \
    if [ "$pinned" != "pnpm@11.24.0" ]; then \
        echo "FATAL: web/package.json pins ${pinned}, this image bakes pnpm@11.24.0." >&2; \
        echo "They must match, or an offline build dies in corepack trying to" >&2; \
        echo "fetch the other one. Update the Dockerfile and rebuild." >&2; \
        exit 1; \
    fi; \
    rm /tmp/package.json; \
    echo "pnpm $(corepack pnpm --version) baked in, matching package.json."

# Next writes here during build; without it the build fails on a read-only or
# root-owned home depending on how the container is run.
ENV NEXT_TELEMETRY_DISABLED=1 \
    HOME=/tmp \
    PNPM_HOME=/tmp/.pnpm \
    CI=1

WORKDIR /app/web
