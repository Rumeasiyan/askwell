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
mapping, never to the answer path. `FixtureWebSearchProvider` is the only
implementation `M6.5-WEB-BE-185` ships — recorded results, for development
and for the eval suite, which needs a provider that could answer without ever
reaching the network (C1). The real one, `ddgs`, is `M6.5-WEB-BE-195`.

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
from datetime import datetime
from typing import Literal, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell import egress
from askwell.audit import Store, record
from askwell.config import ConfigurationError, Settings
from askwell.logging import get_logger

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


# The one place a configuration string maps to an implementation
# (`AGENTS.md` §4 — never a provider name anywhere else in application code).
_PROVIDERS: dict[str, Callable[[], WebSearchProvider]] = {
    "fixture": FixtureWebSearchProvider,
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
    return build()


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

    **Never called again for the same message.** `web_citations` has no
    update path anywhere in this codebase — a stored web result is written
    once and stands as the record of what was read and when, not what a page
    says now (`docs/web-search.md` §4). Reading it back later touches no
    network at all: every value this writes is already what the caller has
    in hand.
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
