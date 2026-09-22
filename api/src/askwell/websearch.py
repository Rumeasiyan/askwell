"""The web search provider behind an interface, called only on explicit
request. `M6.5-WEB-BE-185`.

**Escalation, never fallback (`docs/web-search.md`, C10).** There is exactly
one function in this codebase that ever calls a `WebSearchProvider`'s own
`search()` — `escalate_web_search` below — and it exists to be called from an
accepted, per-question escalation once `M6.5-WEB-SEC-187`/`M6.5-WEB-FE-186`
build that surface. Nothing in `askwell.ask` imports this module: a below-
threshold retrieval abstains and stops there (`M2-ABSTAIN-RET-053`), and the
absence of a path from that abstention into this file is the property
`test_websearch.py`'s zero-calls test exists to protect, not an incidental
fact about the current wiring.

**Behind an interface, like the TTS engine (`docs/architecture.md` §5.2).**
`WebSearchProvider` is the seam; `build_web_search_provider` is the one place
a configuration string (`Settings.web_search_provider`) selects which
implementation answers it, so a provider going away is a change to that one
mapping, never to the answer path. `FixtureWebSearchProvider` is the only
implementation this ticket ships — recorded results, for development and for
the eval suite, which needs a provider that could answer without ever
reaching the network (C1). The real one, `ddgs`, is `M6.5-WEB-BE-195`.

**Every invocation is on the record before it returns**, win or lose
(`M1-ASK-OBS-041`, C6) — an offer the user accepted is never lost even if the
provider then failed or nothing came back.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from askwell.audit import Store, record
from askwell.config import ConfigurationError, Settings
from askwell.logging import get_logger

log = get_logger(__name__)

WEB_SEARCH_ESCALATED = "web_search_escalated"


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
    """
    used_provider = provider if provider is not None else build_web_search_provider(settings)
    provider_name = settings.web_search_provider or "none"

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
            # Dropped, not rendered as an empty citation — this ticket's own
            # edge case. A result kept with an unresolvable URL is untouched
            # here; only a missing passage disqualifies it.
            usable = tuple(item for item in raw_results if item.passage.strip())
            outcome = (
                WebSearchOutcome(status="ok", results=usable)
                if usable
                else WebSearchOutcome(status="no_results")
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
