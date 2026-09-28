"""`_sent_contents` — what a provider request carried, by reference
(`M8-ONLINE-OBS-172`), with the memory facts it carried told apart by origin
(`M9-FIX-FE-212`, #760). The approved disclosure (`askwell.online.DISCLOSURE`)
separates facts the user taught from conclusions Askwell drew on its own, and
the trace built from this record is where the user checks a send against it.
Pure, no network.
"""

import uuid

from askwell.agent.compose import ComposedPrompt
from askwell.ask import _sent_contents
from askwell.memory import MemoryFact, RelevantMemory, SchemaNote


def _composed() -> ComposedPrompt:
    return ComposedPrompt(
        system_prompt="system",
        user_content="user",
        prompt_version="conflicting_sources.v1",
        injection_flagged=False,
        injection_patterns=(),
    )


def _fact(origin: str) -> MemoryFact:
    return MemoryFact(
        id=uuid.uuid4(),
        subject="notice period",
        fact="ninety days",
        origin=origin,
        confidence=None,
        source_id=None,
        source_name=None,
        source_deleted=False,
        created_at=None,
    )


def _note(origin: str) -> SchemaNote:
    return SchemaNote(
        id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        table_name="orders",
        column_name="placed_on",
        description="day first",
        origin=origin,
        confidence=None,
        created_at=None,
    )


def test_an_inferred_fact_is_recorded_as_inferred() -> None:
    taught, inferred = _fact("clarification"), _fact("inferred")
    note = _note("inferred")

    contents = _sent_contents(
        _composed(),
        [],
        clarification_answer=False,
        memory=RelevantMemory(facts=[taught, inferred], notes=[note]),
    )

    assert contents["memory_fact_ids"] == [str(taught.id), str(inferred.id)]
    assert contents["inferred_fact_ids"] == [str(inferred.id)]
    assert contents["schema_note_ids"] == [str(note.id)]


def test_a_confirmed_inference_counts_as_taught() -> None:
    """`memory.confirm_memory_fact` promotes an inferred fact in place to
    `origin = 'correction'`; by the time it is sent it is the user's."""
    confirmed, manual = _fact("correction"), _fact("manual")

    contents = _sent_contents(
        _composed(),
        [],
        clarification_answer=True,
        memory=RelevantMemory(facts=[confirmed, manual], notes=[]),
    )

    assert contents["memory_fact_ids"] == [str(confirmed.id), str(manual.id)]
    assert contents["inferred_fact_ids"] == []


def test_nothing_from_memory_records_empty_lists() -> None:
    contents = _sent_contents(
        _composed(), [], clarification_answer=False, memory=RelevantMemory(facts=[], notes=[])
    )

    assert contents["memory_fact_ids"] == []
    assert contents["inferred_fact_ids"] == []
    assert contents["schema_note_ids"] == []
