"""The online backend: generation by a provider, reached through the egress
proxy under one conversation's authorisation. `M8-ONLINE-BE-170`.

Only generation moves. Retrieval, reranking, the abstention decision, the
citation resolution and every record stay where they were, in
`askwell.ask`, running against the local model and the local database —
which is how "the constraints are not relaxed for the online path" is true
by construction rather than by a second copy of each rule.

**The interface is `StreamChunk`, the local client's own.** The provider
speaks the OpenAI-compatible chat-completions stream, the same shape the
local `llama.cpp` server already offers (`docs/decisions.md`, 2026-08-10),
and this module turns it back into the chunks `askwell.ask` already
consumes. What differs is absorbed here: a chat API takes the system prompt
and the user content as two messages rather than one templated string, and
it has no `<think>` prefill, so the local model's thinking directive is not
sent.

**Every failure is typed, and none of them is fatal to the turn.** Four
reasons a provider call can fail are worth telling apart, because each has a
different fix and none of them is the user's material being wrong: the
network is not there (`NETWORK_UNAVAILABLE`), Askwell's own authorisation
refused the connection (`NOT_AUTHORISED`), the provider said no
(`REFUSED`), or the provider said not now (`RATE_LIMITED`). The rest —
a provider error, a timeout, a malformed stream, a connection lost partway —
is `FAILED` or `INTERRUPTED`. `askwell.ask` answers locally on any of them
and says which it was.

**One request per tunnel.** A fresh client is opened for each call and
closed after it, so the proxy's per-conversation count of permitted
`CONNECT` tunnels is also a count of provider requests (issue #731). A
pooled client would make the two diverge, and the one the user can read is
the proxy's.

**No key is held here.** The caller passes one, or none. Storing it is
`M8-KEY-BE-173`'s, and until that lands nothing passes one, so a real
provider refuses and the turn answers locally saying the provider refused —
which is the true state of an install with no key. A key is never put into
an error message, a log line or the trace: a provider's own error body can
echo part of it back, so the body is never repeated either.

**Every call leaves a `Transmission` behind** (`M8-ONLINE-OBS-172`): where
it went, which model, when, the exact size of the body it handed to the
network, and whether it was handed over at all. The body is serialised here
rather than by `httpx`, so the size recorded is the size of the bytes sent,
not a re-serialisation that could differ by a separator. Its content is not
kept: that is the question and the passages, which the turn already records
by reference and which must not gain a second, unencrypted copy.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from askwell.config import Settings
from askwell.inference.client import CONNECT_TIMEOUT_SECONDS, StreamChunk
from askwell.logging import get_logger

log = get_logger(__name__)

NETWORK_UNAVAILABLE = "network_unavailable"
NOT_AUTHORISED = "not_authorised"
REFUSED = "refused"
RATE_LIMITED = "rate_limited"
FAILED = "failed"
INTERRUPTED = "interrupted"
# A `Transmission`'s outcome when no failure applies: the provider finished
# the answer, or the user stopped the turn while it was streaming.
ANSWERED = "answered"
STOPPED = "stopped"

# The egress proxy's own answers to a `CONNECT` (`askwell.egress`): 403 is
# "no authorisation covers this", 502 is "authorised, and the destination
# could not be reached from this machine".
_PROXY_REFUSED = 403
_PROXY_UNREACHABLE = 502


class OnlineFailed(RuntimeError):
    """The online backend did not produce an answer. `reason_code` says why,
    as one of this module's constants; the message is written for the user
    and never contains a key or a provider's response body."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class OnlineTarget:
    """Everything one call needs, resolved by the caller at send time: where,
    which model, and the conversation's proxy credential."""

    destination: str
    model: str
    proxy_username: str
    proxy_password: str
    api_key: str | None = None


@dataclass(slots=True)
class Transmission:
    """What one call handed to the network. `M8-ONLINE-OBS-172`.

    `content_sent` is False only when the connection was never made — the
    proxy refused the tunnel, or nothing answered at all — because only then
    is it certain the body did not leave. Every other failure, a timeout
    included, counts as sent: over-reporting what left the machine is the
    safe direction to be wrong in.
    """

    destination: str
    model: str
    sent_at: datetime
    request_bytes: int
    content_sent: bool = True
    status_code: int | None = None
    outcome: str | None = None


def target(
    settings: Settings, credentials: tuple[str, str] | None, *, api_key: str | None = None
) -> OnlineTarget | None:
    """The target for a conversation, or None when it cannot go online:
    no provider configured, or no credential held in this process for it."""
    if (
        credentials is None
        or settings.online_ai_destination is None
        or settings.online_ai_model is None
    ):
        return None
    return OnlineTarget(
        destination=settings.online_ai_destination,
        model=settings.online_ai_model,
        proxy_username=credentials[0],
        proxy_password=credentials[1],
        api_key=api_key,
    )


def _proxy_failure(error: httpx.ProxyError, destination: str) -> OnlineFailed:
    status = str(error).split(" ", 1)[0]
    if status == str(_PROXY_UNREACHABLE):
        return OnlineFailed(
            NETWORK_UNAVAILABLE,
            f"Online AI could not reach {destination}: the network is unavailable.",
        )
    if status == str(_PROXY_REFUSED):
        return OnlineFailed(
            NOT_AUTHORISED,
            "Online AI is no longer authorised for this conversation.",
        )
    return OnlineFailed(FAILED, f"Online AI could not connect ({status}).")


def _status_failure(status: int) -> OnlineFailed:
    if status == 429:
        return OnlineFailed(
            RATE_LIMITED, "The online provider is limiting requests right now (429)."
        )
    if 400 <= status < 500:
        return OnlineFailed(REFUSED, f"The online provider refused the request ({status}).")
    return OnlineFailed(FAILED, f"The online provider had an error ({status}).")


class OnlineClient:
    """Streams one answer from the provider. Owns no model name, no
    destination and no key — each comes from `OnlineTarget`."""

    def __init__(
        self,
        settings: Settings,
        online_target: OnlineTarget,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.target = online_target
        # For tests only: a transport replaces the proxy entirely.
        self._transport = transport
        # The most recent call's record, or None before the first.
        self.last_transmission: Transmission | None = None

    @property
    def model(self) -> str:
        return self.target.model

    def _client(self, timeout_seconds: float) -> httpx.AsyncClient:
        timeout = httpx.Timeout(timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS)
        if self._transport is not None:
            return httpx.AsyncClient(transport=self._transport, timeout=timeout)
        # The credential rides in the proxy URL's userinfo, which httpx sends
        # as `Proxy-Authorization: Basic` on the `CONNECT` — the one header
        # the proxy reads to tell this conversation from any other caller.
        proxy = httpx.Proxy(
            f"http://{self.settings.egress_proxy_host}:{self.settings.egress_proxy_port}",
            auth=(self.target.proxy_username, self.target.proxy_password),
        )
        return httpx.AsyncClient(proxy=proxy, timeout=timeout)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "text/event-stream", "Content-Type": "application/json"}
        if self.target.api_key:
            headers["Authorization"] = f"Bearer {self.target.api_key}"
        return headers

    async def stream_generate(
        self,
        system_prompt: str,
        user_content: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
        timeout_seconds: float,
    ) -> AsyncGenerator[StreamChunk, None]:
        """The answer, piece by piece, as `StreamChunk`s — the same shape
        `InferenceClient.stream_generate` yields, ending with one `done`
        chunk whose `truncated` is the provider's `finish_reason: length`.

        Raises only `OnlineFailed`. Whether it is raised before the first
        piece or after some is the caller's to notice.
        """
        url = f"https://{self.target.destination}{self.settings.online_ai_api_path}"
        payload: dict[str, Any] = {
            "model": self.target.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        transmission = Transmission(
            destination=self.target.destination,
            model=self.target.model,
            sent_at=datetime.now(UTC),
            request_bytes=len(body),
        )
        self.last_transmission = transmission
        started = False
        try:
            async with (
                self._client(timeout_seconds) as client,
                client.stream("POST", url, content=body, headers=self._headers()) as response,
            ):
                transmission.status_code = response.status_code
                if response.status_code >= 400:
                    raise _status_failure(response.status_code)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[len("data:") :].strip()
                    if not raw:
                        continue
                    if raw == "[DONE]":
                        transmission.outcome = ANSWERED
                        yield StreamChunk(text="", done=True)
                        return
                    try:
                        event = json.loads(raw)
                        choice = event["choices"][0] if event.get("choices") else {}
                    except (ValueError, KeyError, TypeError, AttributeError) as error:
                        raise OnlineFailed(
                            FAILED, "The online provider streamed something unreadable."
                        ) from error
                    delta = choice.get("delta") if isinstance(choice, dict) else None
                    piece = delta.get("content") if isinstance(delta, dict) else None
                    finish = choice.get("finish_reason") if isinstance(choice, dict) else None
                    if isinstance(piece, str) and piece:
                        started = True
                        yield StreamChunk(text=piece, done=False)
                    if finish:
                        transmission.outcome = ANSWERED
                        yield StreamChunk(text="", done=True, truncated=finish == "length")
                        return
                # The stream ended without saying it was finished: the answer
                # may be cut short, and passing it off as complete would be
                # the silent truncation `docs/ux/ask.md` §5 forbids.
                raise OnlineFailed(
                    INTERRUPTED, "The online provider stopped answering partway through."
                )
        except OnlineFailed as error:
            transmission.outcome = error.reason_code
            raise
        except httpx.ProxyError as error:
            # The proxy refused or could not open the tunnel: the body never
            # left this machine.
            transmission.content_sent = False
            raise _record(transmission, _proxy_failure(error, self.target.destination)) from error
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            transmission.content_sent = False
            raise _record(
                transmission,
                OnlineFailed(
                    NETWORK_UNAVAILABLE,
                    f"Online AI could not reach {self.target.destination}: "
                    "the network is unavailable.",
                ),
            ) from error
        except httpx.TimeoutException as error:
            raise _record(
                transmission,
                OnlineFailed(
                    INTERRUPTED if started else FAILED,
                    f"The online provider did not answer within {timeout_seconds:g}s.",
                ),
            ) from error
        except httpx.HTTPError as error:
            # A tunnel the proxy cut — the authorisation was revoked — or a
            # connection the network dropped. Named by type, never by body.
            raise _record(
                transmission,
                OnlineFailed(
                    INTERRUPTED if started else FAILED,
                    f"The connection to the online provider was lost: {type(error).__name__}.",
                ),
            ) from error
        finally:
            # Reached only with no outcome set when the caller closed the
            # stream partway: the user pressed Stop.
            if transmission.outcome is None:
                transmission.outcome = STOPPED


def _record(transmission: Transmission, failure: OnlineFailed) -> OnlineFailed:
    transmission.outcome = failure.reason_code
    return failure
