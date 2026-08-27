# Askwell API image.
#
# The host needs Podman and nothing else. Python, the dependency resolver, the
# linter, the type checker and the test runner all live in here — the
# development machine runs 3.14, and the AI toolchain (llama-cpp bindings, OCR,
# embeddings) has no 3.14 wheels. A contributor who builds against their host
# Python gets a wheel-build failure on day one with an error that explains
# nothing. So the host Python is never invoked.
#
# Build context is the REPOSITORY ROOT, not api/ — the version comes from the
# root VERSION file and must be present in the image (AGENTS.md §7).
#   podman build -f api/Dockerfile -t askwell-api .

FROM docker.io/library/python:3.12-slim-bookworm AS base

# Fail the build loudly if the base image ever drifts off 3.12. A silent minor
# bump would surface much later as an unbuildable wheel.
RUN set -eu; \
    actual="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"; \
    if [ "$actual" != "3.12" ]; then \
        echo "FATAL: this image must be Python 3.12, found ${actual}." >&2; \
        echo "The project pins 3.12 because the AI toolchain has no wheels" >&2; \
        echo "for newer interpreters. Fix the FROM line, do not relax this." >&2; \
        exit 1; \
    fi; \
    echo "Python ${actual} confirmed."

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Keep uv's cache inside the image so repeat builds reuse layers rather
    # than re-resolving, which also means a later build works with no network.
    UV_CACHE_DIR=/opt/uv-cache \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir "uv>=0.4"

# Tesseract itself, not a Python wheel: `pytesseract` only shells out to this
# binary. `tesseract-ocr-osd` is the orientation/script-detection data
# `M1-EXTRACT-ING-028` needs before recognition; `tesseract-ocr-eng` and
# `tesseract-ocr-tam` are the two traineddata files Askwell ships — English
# for real, Tamil as the hedge recorded in `docs/decisions.md` (recognised,
# never presented as supported). Package names verified against
# packages.debian.org/bookworm before writing them here (`AGENTS.md` §4).
RUN apt-get update && apt-get install --no-install-recommends -y \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-osd \
        tesseract-ocr-tam \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Version first and on its own layer: it changes on nearly every commit, and
# nothing below it needs rebuilding when it does.
COPY VERSION /app/VERSION

# Manifests only, so dependency resolution caches independently of source.
#
# uv.lock is matched by a glob rather than named. Naming a file that is not
# there fails inside COPY with 'stat: no such file or directory', which tells
# a contributor nothing about why the lockfile matters. The glob matches
# nothing when the file is absent — pyproject.toml keeps the pattern set
# non-empty — and the check below gets to explain itself.
COPY api/pyproject.toml api/hatch_build.py api/alembic.ini api/uv.loc[k] /app/api/

WORKDIR /app/api
RUN set -eu; \
    if [ ! -s /app/api/uv.lock ]; then \
        echo "FATAL: api/uv.lock is missing or empty." >&2; \
        echo "" >&2; \
        echo "The lockfile is what makes this build reproducible: without it" >&2; \
        echo "you would silently get different dependency versions than the" >&2; \
        echo "last person, and the difference would surface much later as a" >&2; \
        echo "bug nobody can reproduce. The build will not resolve one for" >&2; \
        echo "you." >&2; \
        echo "" >&2; \
        echo "Restore it:    git checkout api/uv.lock" >&2; \
        echo "Regenerate it: scripts/dev.sh lock   (then review the diff)" >&2; \
        exit 1; \
    fi; \
    # --locked, not --frozen. --frozen installs whatever the lockfile says and
    # never looks at pyproject.toml, so adding a dependency and forgetting to
    # relock produces a build that succeeds while missing it — surfacing much
    # later as an ImportError with no obvious cause. --locked asserts the two
    # agree and fails the build when they do not. It still resolves nothing
    # from the network.
    uv sync --locked --no-install-project --group dev

# Source last: it changes most often, and only this layer rebuilds when it does.
COPY api/src /app/api/src
COPY api/tests /app/api/tests

# --python targets the same environment uv sync populated; without it uv picks
# the system interpreter and the project lands somewhere the tools cannot see.
# --no-deps because they are already installed and pinned above.
RUN uv pip install --python "$UV_PROJECT_ENVIRONMENT/bin/python" --no-deps --editable .

# A default that says something useful when the image is run with no command.
CMD ["python", "-c", "import askwell; print(f'Askwell {askwell.__version__} toolchain image. Run a command: ruff / mypy / pytest.')"]
