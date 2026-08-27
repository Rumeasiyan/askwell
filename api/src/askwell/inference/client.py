"""The client for the native inference process.

One client for generation, embedding and reranking, reached over the Unix
socket the bridge container owns.

The distinction this module exists to preserve: **the assistant being absent is
not the same as a request failing.** `docs/ux/ask.md` §5 degrades to browsing
and search when inference is unavailable rather than showing an error, and it
can only do that if callers can tell the two apart. So `InferenceUnavailable`
and `InferenceFailed` are separate, and nothing here raises a generic error.

No model name appears in this file. Models come from configuration selected by
deployment profile (`docs/architecture.md` §6); a name written into code is a
name that cannot change without a release.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from askwell.config import Settings
from askwell.inference.state import ProcessState
from askwell.inference.state import read as read_state
from askwell.logging import get_logger

log = get_logger(__name__)

# Generous on purpose. `docs/architecture.md` §6 says the light profile is
# "slow but usable", and twenty seconds for a first answer on an 8 GB machine
# is slow-but-usable rather than broken. A tight timeout here would turn the
# cheapest hardware into a product that does not work.
DEFAULT_TIMEOUT_SECONDS = 300.0
CONNECT_TIMEOUT_SECONDS = 5.0


class InferenceUnavailable(RuntimeError):
    """The assistant is not there.

    Distinct from a failed request, because the caller does something
    different: it degrades to search and says so, rather than reporting an
    error the user cannot act on.
    """


class InferenceFailed(RuntimeError):
    """The assistant is there and this request did not work."""


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    tokens: int


class InferenceClient:
    """Talks to llama.cpp over the Unix socket. Owns no model names."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._state_path = settings.inference_socket.parent / "state.json"

    def _client(self, timeout_seconds: float) -> httpx.AsyncClient:
        # Unix socket rather than a host and port: every service is on a
        # network with no route off the machine, so there is no address to
        # dial. The URL host is a placeholder httpx requires and never resolves.
        transport = httpx.AsyncHTTPTransport(uds=str(self.settings.inference_socket))
        return httpx.AsyncClient(
            transport=transport,
            base_url="http://inference",
            timeout=httpx.Timeout(timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS),
        )

    def _require_available(self) -> None:
        """Fail fast with the supervisor's own reason.

        Asking the socket first would produce a connection error, which says
        nothing a user can act on. The supervisor already knows whether the
        model is missing, still loading or out of memory, and those are three
        different things to be told.
        """
        state = read_state(self._state_path)
        if state.state is not ProcessState.READY:
            raise InferenceUnavailable(state.reason or f"The assistant is {state.state}.")

    # The parameter carries its unit rather than being called `timeout`.
    # Partly because the unit belongs in the name, and partly because the value
    # is handed to httpx — which applies it per phase, connect, read and
    # write — so wrapping the call in an outer `asyncio.timeout` as well would
    # give two competing deadlines and a less specific error than either.
    async def _post(
        self, path: str, payload: dict[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        self._require_available()
        try:
            async with self._client(timeout_seconds) as client:
                response = await client.post(path, json=payload)
        except httpx.TimeoutException as error:
            raise InferenceFailed(
                f"The assistant did not answer within {timeout_seconds:g}s. On a light "
                f"profile this can mean the question was long rather than that "
                f"anything is wrong."
            ) from error
        except httpx.HTTPError as error:
            # The socket was there a moment ago and is not answering now: the
            # process went away between the state file and this request.
            raise InferenceUnavailable(
                f"The assistant stopped answering: {type(error).__name__}."
            ) from error

        if response.status_code >= 400:
            raise InferenceFailed(
                f"The assistant refused the request ({response.status_code}): {response.text[:300]}"
            )

        try:
            body: dict[str, Any] = response.json()
        except ValueError as error:
            # Surfaced, never coerced. A malformed response silently turned
            # into an empty answer is an answer the user will believe.
            raise InferenceFailed("The assistant returned something that is not JSON.") from error
        return body

    # --- generation ---------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> Completion:
        body = await self._post(
            "/completion",
            {
                "prompt": prompt,
                "n_predict": max_tokens,
                "temperature": temperature,
                "cache_prompt": True,
            },
            timeout_seconds,
        )
        text = body.get("content")
        if not isinstance(text, str):
            raise InferenceFailed("The assistant's answer had no text in it.")
        tokens = body.get("tokens_predicted")
        return Completion(text=text, tokens=int(tokens) if isinstance(tokens, int) else 0)

    # --- embedding ----------------------------------------------------------

    async def embed(
        self, texts: list[str], *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ) -> list[list[float]]:
        """Embeddings for retrieval.

        The dimension is not checked here. It is fixed by the schema
        (`chunks.embedding` is `vector(n)` with `n` from configuration), so a
        mismatch is a configuration error that the database rejects loudly
        rather than something to silently truncate.
        """
        if not texts:
            return []
        body = await self._post("/v1/embeddings", {"input": texts}, timeout_seconds)
        data = body.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise InferenceFailed(
                f"Asked for {len(texts)} embeddings and got "
                f"{len(data) if isinstance(data, list) else 'something else'}."
            )
        vectors: list[list[float]] = []
        for item in data:
            vector = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(vector, list):
                raise InferenceFailed("An embedding came back without a vector.")
            vectors.append([float(value) for value in vector])
        return vectors

    # --- reranking ----------------------------------------------------------

    async def rerank(
        self, query: str, documents: list[str], *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ) -> list[tuple[int, float]]:
        """Score documents against a query, best first.

        Returns indices into `documents` rather than the documents themselves:
        the caller has the passages and their provenance already, and copying
        text through a scoring call is how a citation loses the chunk it came
        from.
        """
        if not documents:
            return []
        body = await self._post(
            "/v1/rerank", {"query": query, "documents": documents}, timeout_seconds
        )
        results = body.get("results")
        if not isinstance(results, list):
            raise InferenceFailed("The assistant's ranking had no results in it.")

        scored: list[tuple[int, float]] = []
        for item in results:
            if not isinstance(item, dict) or "index" not in item:
                raise InferenceFailed("A ranking result had no index.")
            scored.append((int(item["index"]), float(item.get("relevance_score", 0.0))))
        return sorted(scored, key=lambda pair: pair[1], reverse=True)
