"""The web search provider behind an interface, called only on explicit
request. `M6.5-WEB-BE-185`, egress authorisation `M6.5-WEB-SEC-187`.

**Escalation, never fallback (`docs/web-search.md`, C10).** There is exactly
one function in this codebase that ever calls a `WebSearchProvider`'s own
`search()` — `escalate_web_search` below — and it exists to be called from an
accepted, per-question escalation once `M6.5-WEB-FE-186` builds that surface.
Nothing in `askwell.ask` imports this module: a below-threshold retrieval
abstains and stops there (`M2-ABSTAIN-RET-053`), and the absence of a path
from that abstention into this file is the property `test_websearch.py`'s
zero-calls test exists to protect, not an incidental fact about the current
wiring.

**Behind an interface, like the TTS engine (`docs/architecture.md` §5.2).**
`WebSearchProvider` is the seam; `build_web_search_provider` is the one place
a configuration string (`Settings.web_search_provider`) selects which
implementation answers it, so a provider going away is a change to that one
mapping, never to the answer path. `FixtureWebSearchProvider` is what
`M6.5-WEB-BE-185` shipped — recorded results, for development and for the
eval suite, which needs a provider that could answer without ever reaching
the network (C1). `DDGSWebSearchProvider`, `M6.5-WEB-BE-195`, is the real one.

**`DDGSWebSearchProvider` is pinned to the single `"duckduckgo"` backend, not
`ddgs`'s own `"auto"`.** `ddgs` can fan a search across several engines, each
its own host — the egress grant this module opens (below) is scoped to one
destination per turn, and `"auto"` would need as many as `ddgs` chose to
try. The `duckduckgo` backend alone posts to
`https://html.duckduckgo.com/html/`, which is exactly
`Settings.web_search_destination_host`/`_port`'s existing value — that
default was already the real endpoint, not a placeholder needing to change.
Results carry only the snippet `ddgs` itself returns as `passage`; nothing
here calls `askwell.webfetch.fetch_pages` on the result URLs, which would
mean fetching arbitrary third-party hosts the single-destination grant
cannot express without redesigning `askwell.egress` itself — out of this
ticket's scope, and recorded as a follow-up (`docs/decisions.md`, this
date).

**Every invocation is on the record before it returns**, win or lose
(`M1-ASK-OBS-041`, C6) — an offer the user accepted is never lost even if the
provider then failed or nothing came back.

**The egress grant is opened and closed here, around the provider call
alone** (`M6.5-WEB-SEC-187`, `docs/architecture.md` §5.1). `escalate_web_search`
is the sole caller of `askwell.egress.open_grant`/`close_grant` for the
search destination, scoped to this turn's `message_id` and closed in
`finally` regardless of how the call ends — normally, on a caught provider
failure, or on this coroutine being cancelled. The proxy still enforces the
grant independently: even if application code opened one without a real
acceptance behind it, `open_grant`'s own `accepted` argument refuses it at
the mechanism, not by trusting this module's docstring.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from ddgs import DDGS
from ddgs.exceptions import DDGSException
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import egress
from askwell.agent.claims import segment_claims
from askwell.audit import Store, record
from askwell.config import ConfigurationError, Settings
from askwell.db.engine import session_scope
from askwell.inference.client import InferenceClient, InferenceFailed, InferenceUnavailable
from askwell.logging import get_logger

# `askwell.agent.compose` imports `WebSearchResult` from this module — a
# module-level import the other way would be circular, since it would run
# while this module is still mid-definition (`WebSearchResult` not yet bound)
# whenever something imports `askwell.websearch` first. Deferred into
# `compose_and_generate_web_answer` below instead, where both modules have
# already finished loading.

log = get_logger(__name__)

WEB_SEARCH_ESCALATED = "web_search_escalated"
WEB_SEARCH_GRANT_OPENED = "web_search_grant_opened"
WEB_SEARCH_GRANT_CLOSED = "web_search_grant_closed"


@dataclass(frozen=True, slots=True)
class WebSearchResult:
    """One result from a provider: `docs/web-search.md` §4's four fields plus
    the retrieval timestamp that keeps a citation honest after the page it
    points at changes or disappears."""

    source: str
    """The domain the result came from, e.g. `"example.com"`."""

    title: str
    url: str
    passage: str
    retrieved_at: datetime


class WebSearchUnavailable(RuntimeError):
    """The provider could not be reached, or did not answer in time.

    Distinct from an empty result list, which means the provider *was*
    reached and had nothing to offer — this ticket's own edge case: "nothing
    matched" is a real, distinct result, not an error, so the surface can say
    so plainly rather than falling back further.
    """


class WebSearchProvider(Protocol):
    """Question in, results out. The one seam a provider swap ever touches."""

    async def search(self, question: str) -> list[WebSearchResult]:
        """Return results for `question`, or raise `WebSearchUnavailable`.

        An empty list means nothing matched. A result may come back with an
        empty passage — dropped by the caller, never rendered as an empty
        citation — so an implementation need not filter that itself.
        """
        ...


class FixtureWebSearchProvider:
    """Recorded results, keyed by the exact question text.

    Used for development and by the eval suite, both of which need a
    provider that can answer without a real one existing yet — the eval
    suite's own job is asserting that **no** fetch happens at all
    (`M6.5-EVAL-TEST-194`), so it must never be handed anything that could
    reach the network. A question with no recorded fixture is "nothing
    matched" rather than an error: a fixture only knows what it was given,
    and an unrecognised query is not the same failure as an unreachable
    provider.
    """

    def __init__(self, results: Mapping[str, Sequence[WebSearchResult]] | None = None) -> None:
        self._results: dict[str, tuple[WebSearchResult, ...]] = (
            {question: tuple(items) for question, items in results.items()}
            if results is not None
            else {}
        )

    async def search(self, question: str) -> list[WebSearchResult]:
        return list(self._results.get(question, ()))


class DDGSWebSearchProvider:
    """The real provider. `ddgs` — MIT, keyless, no account, no cost
    (`docs/web-search.md` §6, `docs/decisions.md` 2026-08-26). Pinned to the
    `"duckduckgo"` backend alone; see this module's own docstring for why.

    `ddgs` is synchronous — `DDGS.text` runs its own thread pool internally
    even for one backend — so `search` below runs it via `asyncio.to_thread`
    rather than blocking the event loop `escalate_web_search` awaits it on.

    The egress proxy is a forward proxy (`askwell.egress.EgressProxy`), not
    transparent routing: a client has to be told to use it, the way
    `askwell.webfetch`'s `httpx.AsyncClient` already is implicitly through
    `HTTP_PROXY`/`HTTPS_PROXY` (`compose.yaml`). `ddgs` does not read those —
    `DDGS.__init__` only ever consults its own `proxy` argument or
    `DDGS_PROXY` — so this passes `Settings.egress_proxy_host`/`_port`
    explicitly rather than depending on undocumented behaviour in `primp`,
    the Rust HTTP client `ddgs` is built on.
    """

    _BACKEND = "duckduckgo"

    def __init__(
        self,
        settings: Settings,
        *,
        search_fn: Callable[[str], list[dict[str, Any]]] | None = None,
    ) -> None:
        self._proxy = f"http://{settings.egress_proxy_host}:{settings.egress_proxy_port}"
        self._timeout_seconds = settings.web_search_timeout_seconds
        # Injectable for tests, which must stay network-free like every other
        # unmarked test (`AGENTS.md` §6) — `_ddgs_text` below is what a real
        # deployment uses, never exercised directly by this module's tests.
        self._search_fn = search_fn or self._ddgs_text

    def _ddgs_text(self, question: str) -> list[dict[str, Any]]:
        with DDGS(proxy=self._proxy, timeout=max(1, ceil(self._timeout_seconds))) as ddgs:
            result: list[dict[str, Any]] = ddgs.text(question, backend=self._BACKEND)
            return result

    async def search(self, question: str) -> list[WebSearchResult]:
        try:
            raw_results = await asyncio.to_thread(self._search_fn, question)
        except DDGSException as error:
            raise WebSearchUnavailable(str(error)) from error
        retrieved_at = datetime.now(UTC)
        results: list[WebSearchResult] = []
        for item in raw_results:
            href = str(item.get("href") or "").strip()
            if not href:
                continue
            results.append(
                WebSearchResult(
                    source=urlsplit(href).netloc,
                    title=str(item.get("title") or ""),
                    url=href,
                    passage=str(item.get("body") or ""),
                    retrieved_at=retrieved_at,
                )
            )
        return results


# The one place a configuration string maps to an implementation
# (`AGENTS.md` §4 — never a provider name anywhere else in application code).
_PROVIDERS: dict[str, Callable[[Settings], WebSearchProvider]] = {
    "fixture": lambda _settings: FixtureWebSearchProvider(),
    "ddgs": DDGSWebSearchProvider,
}


def build_web_search_provider(settings: Settings) -> WebSearchProvider | None:
    """The implementation `Settings.web_search_provider` selects, or `None`.

    `None` means no provider is configured — the ticket's own "configuration
    removed entirely" edge case — and `escalate_web_search` treats that
    identically to the provider being unreachable, so the escalation is
    offered as unavailable rather than the process crashing. An unrecognised
    name fails loudly instead (`AGENTS.md` §6): a typo in configuration is a
    mistake worth surfacing at the point it is read, not silently downgraded
    to "unavailable" alongside a genuine outage.
    """
    if settings.web_search_provider is None:
        return None
    try:
        build = _PROVIDERS[settings.web_search_provider]
    except KeyError as error:
        raise ConfigurationError(
            f"ASKWELL_WEB_SEARCH_PROVIDER={settings.web_search_provider!r} is not a known "
            f"web search provider. Known providers: {sorted(_PROVIDERS)}."
        ) from error
    return build(settings)


@dataclass(frozen=True, slots=True)
class WebSearchOutcome:
    """What one escalation produced, distinguishing every state a caller
    needs to render distinctly rather than folding them into "no results"."""

    status: Literal["ok", "no_results", "unavailable"]
    results: tuple[WebSearchResult, ...] = ()
    reason: str | None = None
    """Set only for `"unavailable"` — not configured, unreachable, or timed
    out. Never shown to the user as-is; the surface says the provider could
    not be reached, not whose fault it was (`docs/web-search.md` §6)."""


def _search_destination(settings: Settings) -> str | None:
    """The `host:port` the turn's egress grant is scoped to, or `None` when
    no provider is configured at all — there is nothing to grant access to
    if nothing will ever try to reach it. `M6.5-WEB-SEC-187`."""
    if settings.web_search_provider is None:
        return None
    return f"{settings.web_search_destination_host}:{settings.web_search_destination_port}"


async def escalate_web_search(
    settings: Settings,
    db: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    question: str,
    provider: WebSearchProvider | None = None,
) -> WebSearchOutcome:
    """The single call site. Only ever reached from an accepted, per-question
    escalation — see this module's own docstring for what that means
    structurally.

    `provider` is an injection point for tests and for a future caller that
    already resolved one; when omitted, `build_web_search_provider(settings)`
    supplies it, so a caller with nothing special to inject still gets
    whatever configuration selects.

    **The egress grant is opened here and closed in `finally`** —
    `M6.5-WEB-SEC-187`. `message_id` is this turn's own identifier, and the
    grant is scoped to it: closed the instant this function returns, by
    whichever route it returns — an ordinary result, a caught provider
    failure folded into `"unavailable"`, or the caller cancelling this
    coroutine (the browser stopping generation mid-search). `try`/`finally`
    covers all three identically, which is the point — a failure path that
    leaks a grant is worse than the failure itself.
    """
    used_provider = provider if provider is not None else build_web_search_provider(settings)
    provider_name = settings.web_search_provider or "none"
    destination = _search_destination(settings)
    turn_id = str(message_id)

    grant_opened = False
    if destination is not None:
        grant_opened = await egress.open_grant(
            settings,
            turn_id=turn_id,
            destination=destination,
            accepted=True,
            ttl_seconds=settings.web_search_grant_ttl_seconds,
        )
        if grant_opened:
            await record(
                db,
                Store.INTERACTIONS,
                WEB_SEARCH_GRANT_OPENED,
                {
                    "conversation_id": str(conversation_id),
                    "message_id": turn_id,
                    "destination": destination,
                },
            )

    try:
        if used_provider is None:
            outcome = WebSearchOutcome(status="unavailable", reason="no provider configured")
        else:
            try:
                raw_results = await asyncio.wait_for(
                    used_provider.search(question), timeout=settings.web_search_timeout_seconds
                )
            except TimeoutError:
                outcome = WebSearchOutcome(status="unavailable", reason="timed out")
            except WebSearchUnavailable as error:
                outcome = WebSearchOutcome(status="unavailable", reason=str(error))
            else:
                # Dropped, not rendered as an empty citation — this ticket's
                # own edge case. A result kept with an unresolvable URL is
                # untouched here; only a missing passage disqualifies it.
                usable = tuple(item for item in raw_results if item.passage.strip())
                outcome = (
                    WebSearchOutcome(status="ok", results=usable)
                    if usable
                    else WebSearchOutcome(status="no_results")
                )
    finally:
        if grant_opened:
            await egress.close_grant(settings, turn_id)
            await record(
                db,
                Store.INTERACTIONS,
                WEB_SEARCH_GRANT_CLOSED,
                {
                    "conversation_id": str(conversation_id),
                    "message_id": turn_id,
                    "destination": destination,
                },
            )

    # C6/`M1-ASK-OBS-041`: on the interaction record before returning, win or
    # lose, so an accepted escalation is never lost even when the provider
    # then failed. No result content here — that is `M6.5-WEB-BE-189`'s own
    # store, with the retrieval timestamps; this row is the fact that the
    # escalation happened and what came of it.
    await record(
        db,
        Store.INTERACTIONS,
        WEB_SEARCH_ESCALATED,
        {
            "conversation_id": str(conversation_id),
            "message_id": str(message_id),
            "question": question,
            "provider": provider_name,
            "status": outcome.status,
            "reason": outcome.reason,
            "result_count": len(outcome.results),
        },
    )
    log.info(
        "web_search_escalated",
        conversation_id=str(conversation_id),
        message_id=str(message_id),
        provider=provider_name,
        status=outcome.status,
    )
    return outcome


@dataclass(frozen=True, slots=True)
class WebCitationRecord:
    """One web result that was actually used in a claim, ready to write to
    `web_citations`. `M6.5-WEB-BE-189`.

    Deliberately not `WebSearchResult` itself: a result the provider returned
    and a result a claim actually cited are different things — `docs/backlog/
    M6.5-it-can-look-outside.md` ticket `M6.5-WEB-BE-189`'s own edge case, "a
    result retrieved but ultimately not used in any claim — not stored as a
    citation." `claim_ordinal` is what ties this row to the sentence that
    used it, the same role `Citation.claim_ordinal` plays for a document
    citation — `askwell.agent.claims.segment_claims`/`M1-CITE-BE-042`.
    """

    claim_ordinal: int
    domain: str
    title: str
    url: str
    passage: str
    retrieved_at: datetime


def web_citation_record(result: WebSearchResult, claim_ordinal: int) -> WebCitationRecord:
    """Build the row a cited `WebSearchResult` writes to `web_citations` —
    the domain, title, URL, passage and retrieval timestamp the provider
    already returned, tied to the claim that used it."""
    return WebCitationRecord(
        claim_ordinal=claim_ordinal,
        domain=result.source,
        title=result.title,
        url=result.url,
        passage=result.passage,
        retrieved_at=result.retrieved_at,
    )


async def record_web_citations(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    records: Sequence[WebCitationRecord],
) -> None:
    """Write `records` to `web_citations`, in whatever transaction `db` is
    already part of — the same one the caller writes the `messages` row and
    `citations` rows in, so a web citation is never left standing for a turn
    whose own answer failed to save (`docs/backlog/M6.5-it-can-look-outside
    .md` ticket `M6.5-WEB-BE-189`'s own Scope: "written in the same
    transaction as the answer they support").

    **No update path anywhere in this codebase.** A stored web result is
    written once and stands as the record of what was read and when, not
    what a page says now (`docs/web-search.md` §4) — calling this again for
    the same `message_id`, once per accepted escalation on that turn
    (`ask_escalate_web`'s own "search the web" twice edge case), adds more
    rows rather than ever touching an earlier one. Reading it back later
    touches no network at all: every value this writes is already what the
    caller has in hand.
    """
    for row in records:
        await db.execute(
            text(
                "INSERT INTO web_citations "
                "(id, message_id, claim_ordinal, domain, title, url, passage, retrieved_at) "
                "VALUES (:id, :message_id, :claim_ordinal, :domain, :title, :url, :passage, "
                ":retrieved_at)"
            ),
            {
                "id": uuid.uuid4(),
                "message_id": message_id,
                "claim_ordinal": row.claim_ordinal,
                "domain": row.domain,
                "title": row.title,
                "url": row.url,
                "passage": row.passage,
                "retrieved_at": row.retrieved_at,
            },
        )


async def compose_and_generate_web_answer(
    settings: Settings,
    *,
    question: str,
    results: Sequence[WebSearchResult],
    client: InferenceClient | None = None,
) -> tuple[str, list[WebCitationRecord]] | None:
    """The escalation's own answer, generated from `results` alone —
    `M6.5-WEB-FE-191`. `None` when the model could not be reached at all, the
    same `InferenceUnavailable`/`InferenceFailed` distinction
    `askwell.ask._run_generation` already treats as recoverable rather than
    fatal: the escalation itself still succeeded (the fetch happened, the
    grant opened and closed, the interaction is on the record), only the
    answer over it could not be composed, so the caller degrades rather than
    losing the whole response to an unhandled error.

    A second, narrower generation call rather than re-running the turn's own
    — the candidates that produced the original abstained or partial answer
    are not available here to recombine into one prompt (`docs/decisions.md`,
    this date). `compose_web_answer` (`askwell.agent.compose`) reuses the same
    `answer_composition.v1.md` system prompt and the same `<web-content>`
    delimitation every other turn's generation already carries, so a claim
    drawn from `results` is bound by the identical C7 boundary.

    **Claim ordinals in the returned records are local to this answer alone**
    — 1-based, counting only this text's own claim-bearing sentences
    (`askwell.agent.claims.segment_claims`). `ask_escalate_web` is what
    offsets them into the turn's shared numbering space, once it knows how
    many claims the turn's stored answer already carries; this function has
    no reason to know that and stays testable without it.
    """
    # Deferred: `askwell.agent.compose` imports `WebSearchResult` from this
    # module, so a module-level import here would be circular.
    from askwell.agent.compose import compose_web_answer

    used_client = client if client is not None else InferenceClient(settings)
    composed = compose_web_answer(question, results)
    prompt = f"{composed.system_prompt}\n\n{composed.user_content}"
    try:
        completion = await used_client.generate(prompt, max_tokens=settings.generation_max_tokens)
    except (InferenceUnavailable, InferenceFailed):
        return None

    records: list[WebCitationRecord] = []
    for claim in segment_claims(completion.text):
        for index in claim.indices:
            if 1 <= index <= len(results):
                records.append(web_citation_record(results[index - 1], claim.ordinal))
    return completion.text, records


class WebEscalateRequest(BaseModel):
    """The question the client is escalating — this turn's own question,
    carried back rather than re-read from `messages`, since the row this
    endpoint loads is the assistant turn, not the user one that asked it."""

    question: str


def register_web_search(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Attach the one HTTP route `M6.5-WEB-FE-186`'s escalation offer calls:
    `POST /ask/{message_id}/escalate/web`. `escalate_web_search` (above) is
    the whole implementation; this is the boundary that decides whether a
    given `message_id` is even allowed to reach it.

    **The turn must have actually abstained or answered partially** — issue
    #532, filed against this exact endpoint before it existed: the frontend
    offer only ever renders below an abstention or a partial answer's named
    gap, so in normal use this check never fires, but C10's guarantee ("the
    offer is the only route to a search") is stated elsewhere in this
    codebase as a structural property of the *server*, not a rendering
    convention of one screen — `test_the_full_answer_path_never_calls_the_
    provider` (`test_websearch.py`) already treats it that way. Checking here
    is what makes a direct `POST` against a fully-grounded turn refused by
    the mechanism rather than merely undrawn by the UI.

    Abstained: `content` is empty and `trace ->> 'reason'` is set — the same
    test `lib/ask.ts`'s `isAbstained` uses client-side (`messages.trace` is
    where `_run_generation` writes both). Partial: `trace ->> 'partial_coverage'`
    is true (`M2-PARTIAL-BE-057`). Neither → 409, matching the 409 shape
    `ask_clarify_resolve` already uses for "this turn is not in the state
    this action requires."
    """

    @app.get("/settings/web-search")
    async def settings_web_search() -> JSONResponse:
        """Whether the escalation offer's web option has anywhere to send a
        question — `docs/ux/web-search.md` §4's "Search unavailable" state,
        which must say so plainly rather than the control disappearing
        (`M6.5-WEB-FE-186`'s own Edge Cases). Read once, on render, rather
        than the offer discovering unavailability only after the user has
        already clicked."""
        return JSONResponse({"available": settings.web_search_provider is not None})

    @app.post("/ask/{message_id}/escalate/web")
    async def ask_escalate_web(message_id: uuid.UUID, body: WebEscalateRequest) -> JSONResponse:
        async with session_scope(factory) as db:
            row = (
                await db.execute(
                    text(
                        "SELECT conversation_id, content, trace FROM messages "
                        "WHERE id = :id AND role = 'assistant'"
                    ),
                    {"id": message_id},
                )
            ).first()
            if row is None:
                return JSONResponse({"error": "Askwell has no turn with that id."}, status_code=404)
            conversation_id, content, trace = row
            trace = trace if isinstance(trace, dict) else {}
            abstained = content == "" and trace.get("reason") is not None
            partial = bool(trace.get("partial_coverage"))
            if not (abstained or partial):
                return JSONResponse(
                    {"error": "That turn did not abstain or answer partially."}, status_code=409
                )

            # `M6.5-WEB-FE-186`'s own Audit/Logging Requirement: "Accepting
            # is a decisions record — the user authorised content to leave
            # the machine." Recorded on acceptance itself, in `Store.DECISIONS`
            # rather than `Store.INTERACTIONS` (where `escalate_web_search`
            # below logs what came of it) — the two answer different
            # questions, "did the user authorise this" and "what happened
            # when it ran," and C6 treats a decision as its own kind of
            # record independent of outcome.
            await record(
                db,
                Store.DECISIONS,
                "web_search_escalation_accepted",
                {
                    "conversation_id": str(conversation_id),
                    "message_id": str(message_id),
                    "question": body.question,
                },
            )

            outcome = await escalate_web_search(
                settings,
                db,
                conversation_id=conversation_id,
                message_id=message_id,
                question=body.question,
            )

            # `M6.5-WEB-FE-191`: results alone are not an answer — the
            # margin cites a passage, but this endpoint used to hand the
            # browser nothing to cite a web result *as* a claim with, so
            # `WebResultsRegion` (`M6.5-WEB-FE-190`) had nowhere to be
            # rendered from. Generated only when there is something usable
            # to generate from — `"no_results"`/`"unavailable"` leave
            # `answer_text`/`citation_payload` at their defaults, which is
            # `M6.5-WEB-FE-192`'s own states to render, untouched here.
            answer_text: str | None = None
            citation_payload: list[dict[str, Any]] = []
            if outcome.status == "ok":
                generated = await compose_and_generate_web_answer(
                    settings, question=body.question, results=outcome.results
                )
                if generated is not None:
                    web_text, local_records = generated
                    if local_records:
                        # `content` still names the turn's answer as it stood
                        # immediately before this escalation. An earlier
                        # escalation on the same turn has already appended
                        # its own text to it (the `UPDATE` below) by the time
                        # a second one runs, so counting claims in `content`
                        # here continues the turn's shared ordinal space
                        # rather than restarting it — the same "read back
                        # what is already there" approach this endpoint
                        # already takes to `content`/`trace` above.
                        ordinal_offset = len(segment_claims(content))
                        offset_records = [
                            WebCitationRecord(
                                claim_ordinal=ordinal_offset + local.claim_ordinal,
                                domain=local.domain,
                                title=local.title,
                                url=local.url,
                                passage=local.passage,
                                retrieved_at=local.retrieved_at,
                            )
                            for local in local_records
                        ]
                        await record_web_citations(
                            db, message_id=message_id, records=offset_records
                        )
                        # Persisted so a second escalation's own `content`
                        # read (above, next time this endpoint runs) and a
                        # reload within the same session both see the full
                        # answer — `messages.content` is already updated this
                        # way at the end of an ordinary turn's own generation
                        # (`ask.py`), not a pattern invented here.
                        await db.execute(
                            text("UPDATE messages SET content = content || :suffix WHERE id = :id"),
                            {"suffix": f"\n\n{web_text}", "id": message_id},
                        )
                        answer_text = web_text
                        citation_payload = [
                            {
                                "claim_ordinal": record_.claim_ordinal,
                                "domain": record_.domain,
                                "title": record_.title,
                                "url": record_.url,
                                "passage": record_.passage,
                                "retrieved_at": record_.retrieved_at.isoformat(),
                            }
                            for record_ in offset_records
                        ]

        return JSONResponse(
            {
                "status": outcome.status,
                "reason": outcome.reason,
                "result_count": len(outcome.results),
                "answer_text": answer_text,
                "citations": citation_payload,
            }
        )
