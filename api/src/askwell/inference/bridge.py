"""The Unix socket the containers reach inference through.

This runs in a container, and it has to. SELinux refuses `connectto` when a
`container_t` process dials a socket listened on by an `unconfined_t` one — and
the host supervisor is unconfined. The *file's* label is irrelevant; the
listener's *process* label decides. Verified from the audit log:

    AVC denied { connectto } ... comm="askwell-api"
      scontext=...container_t  tcontext=...unconfined_t
      tclass=unix_stream_socket

So: the host supervises llama.cpp on loopback, this bridges a Unix socket to
it, and the API and worker connect to the socket. `container_t` to
`container_t`, which is allowed.

This is the one container with host networking, and that is a real widening of
the claim in `docs/architecture.md` §5 rather than a technicality. It is kept
to this file for that reason: every line of it dials `127.0.0.1` and nothing
else, which is a guarantee you get by reading it rather than one the network
enforces. Everything that handles the user's material — the API, the worker,
the database, the queue — stays on the internal network with no route out.
"""

import asyncio
import contextlib
import os
from pathlib import Path

from askwell.config import Environment, Settings, load_settings
from askwell.logging import configure_logging, get_logger

log = get_logger(__name__)

# The only address this program will ever connect to.
UPSTREAM_HOST = "127.0.0.1"

# Which upstream serves which path.
#
# One llama.cpp process cannot serve all three roles: `--reranking` needs a
# reranker model and is mutually exclusive with generation, and a generation
# model's embeddings are the wrong width for the schema entirely (issue #89).
# So there are three processes, and one socket in front of them — the
# containers should not have to know how many there are, or on which ports.
#
# Routed by path prefix rather than by parsing the whole request: the prefix is
# in the first line, which is already read, and anything cleverer would be a
# second HTTP implementation to keep correct.
ROUTES: tuple[tuple[str, str, str], ...] = (
    ("/v1/embeddings", "embedding", "ASKWELL_EMBEDDING_PORT"),
    ("/embedding", "embedding", "ASKWELL_EMBEDDING_PORT"),
    ("/v1/rerank", "reranking", "ASKWELL_RERANKER_PORT"),
    ("/rerank", "reranking", "ASKWELL_RERANKER_PORT"),
)


async def _pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (OSError, asyncio.CancelledError):
        pass
    finally:
        writer.close()
        with contextlib.suppress(OSError, asyncio.CancelledError):
            await writer.wait_closed()


def _prepare_socket_path(path: Path) -> None:
    """Create the directory and clear a stale socket, synchronously.

    Blocking filesystem calls, done once at startup before anything is being
    served — which is why they are here rather than inline in the async
    function. A socket file left by a previous run refuses connections rather
    than being replaced, and the resulting error names an address rather than
    a stale file, which sends whoever reads it looking in the wrong place.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def _route(settings: Settings, request_line: bytes) -> tuple[int, str]:
    """Which process should answer this, by path.

    Generation is the default rather than an error, because llama.cpp serves a
    good deal more than the three endpoints named here — `/health`, `/props`,
    `/tokenize` — and refusing everything unrecognised would break them for no
    benefit. A wrong guess reaches a process that answers 404 itself, which is
    a better failure than this file inventing one.
    """
    try:
        path = request_line.decode("latin-1").split(" ")[1]
    except (UnicodeDecodeError, IndexError):
        return settings.inference_upstream_port, "generation"

    for prefix, role, variable in ROUTES:
        if path.startswith(prefix):
            port = (
                settings.embedding_port
                if variable == "ASKWELL_EMBEDDING_PORT"
                else settings.reranker_port
            )
            return port, role

    return settings.inference_upstream_port, "generation"


async def serve(settings: Settings) -> None:
    path = Path(settings.inference_socket)
    _prepare_socket_path(path)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # The request line is read here rather than streamed straight through,
        # because the path decides which process answers. It is put back in
        # front of the rest of the stream afterwards, so nothing downstream
        # sees a request with its first line missing.
        try:
            async with asyncio.timeout(30):
                request_line = await reader.readline()
        except (TimeoutError, OSError):
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
            return

        port, role = _route(settings, request_line)

        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(UPSTREAM_HOST, port)
        except OSError as error:
            # Inference is down. Closing is the honest answer: the supervisor's
            # state file already says why, and inventing an HTTP error here
            # would make this a second place that explains inference failures,
            # with less to go on.
            log.warning("inference_upstream_down", role=role, port=port, error=str(error))
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
            return

        upstream_writer.write(request_line)
        await upstream_writer.drain()
        await asyncio.gather(_pump(reader, upstream_writer), _pump(upstream_reader, writer))

    server = await asyncio.start_unix_server(handle, path=str(path))
    # The API runs in a different container with a different user namespace.
    # This is a socket in the user's own directory on a single-user machine,
    # not a permission boundary — the boundary is that nothing off this machine
    # can reach it at all.
    os.chmod(path, 0o666)
    log.info(
        "inference_bridge_listening",
        socket=str(path),
        generation=f"{UPSTREAM_HOST}:{settings.inference_upstream_port}",
        embedding=f"{UPSTREAM_HOST}:{settings.embedding_port}",
        reranking=f"{UPSTREAM_HOST}:{settings.reranker_port}",
    )
    async with server:
        await server.serve_forever()


def main() -> None:
    settings = load_settings()
    configure_logging(
        level=settings.log_level,
        json_output=settings.environment is not Environment.DEVELOPMENT,
    )
    try:
        asyncio.run(serve(settings))
    except KeyboardInterrupt:  # pragma: no cover - a signal, not a code path
        log.info("inference_bridge_stopped")
