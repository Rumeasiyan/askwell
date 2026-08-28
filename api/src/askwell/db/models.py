"""The v1 data model. `docs/architecture.md` §7.

Single user, single machine. There are no `organisations`, no `users` and no
roles — those were removed with the repositioning, and their absence here is
deliberate rather than an omission to be filled in later.

Two distinctions run through this file and neither may be collapsed.

**Deletion is not supersession.** `superseded_by` records that a newer version
of a thing exists. `deleted_at` is a tombstone. Reusing one for the other loses
either the version history or the ability to resolve an old citation to
"deleted on the 3rd", and both losses are silent.

**A citation is a row, not a field in a JSON blob.** C4 requires every factual
claim to carry one, and `docs/success-metrics.md` §2 tracks uncited claims as a
counter-metric at 100%. A constraint nobody can query is a constraint nobody
can enforce.
"""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from askwell.db.base import Base, created_at, uuid_pk

# --- vocabularies -----------------------------------------------------------
# Stored as text with a CHECK rather than a native Postgres enum. Adding a value
# to a native enum is a migration that cannot run inside a transaction with
# other statements on older servers, and removing one is worse. The check is
# just as strict and the diff is readable.

SOURCE_KINDS = ("file", "csv", "dump", "connection")
# `queued` is the state a row is created in: recorded, hashed, and waiting for
# an ingester that has not started on it. It is separate from `indexing`
# because they are different answers to "what is happening to my file right
# now" — one of them is "nothing yet, and here is what has to arrive first",
# and rendering that as *Indexing* is a progress bar that does not move.
SOURCE_STATUSES = ("queued", "indexing", "ready", "attention", "deleted")
DOCUMENT_STATUSES = ("queued", "indexing", "ready", "attention", "deleted")
NOTE_ORIGINS = ("user", "inferred")
MEMORY_ORIGINS = ("clarification", "correction", "manual")
CLARIFICATION_STATUSES = ("pending", "answered", "skipped", "dismissed")
# What one document's trip through the ingestion pipeline can be doing.
# `parked` is the one that needs saying out loud: the job ran, it reached a
# stage that has not been built yet, and it stopped there rather than claiming
# to have finished. It is not a failure and it is not success, and collapsing
# it into either would make the library render a lie in one direction or the
# other. See `askwell.ingest`.
INGEST_STATES = ("queued", "running", "parked", "failed", "done")
CONVERSATION_MODES = ("text", "voice")
AI_BACKENDS = ("local", "online")
MESSAGE_ROLES = ("user", "assistant", "system")
FACT_KINDS = ("memory", "schema_note")


# Defaults are `server_default`, never SQLAlchemy's Python-side `default`.
# A Python-side default exists only for rows the ORM inserts, so a migration, a
# `psql` session or a repair script hits a NOT NULL violation on a column that
# looked like it had a default. The invariant belongs in the database.


def _one_of(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    listed = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({listed})", name=name)


# --- settings ---------------------------------------------------------------


class Setting(Base):
    """Key/value application settings: profile, retention, thresholds.

    Deliberately not one row of many columns. Every setting added later would
    otherwise be a migration on a user's own laptop.
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = created_at()


# --- nominated roots --------------------------------------------------------


class Root(Base):
    """A directory the user has nominated as one Askwell may read.

    Askwell indexes in place, so the containers need a route to the user's own
    folders. This table *is* that permission: `askwell.roots.covering()` reads
    it before anything opens a file, and a path no row here covers is never
    read.

    Its own table rather than a row in `settings`. A JSON list under a settings
    key cannot be joined against, cannot carry a per-root timestamp, and cannot
    be tombstoned — and the tombstone is the point. Removing a root has to
    leave enough behind for a source under it to say *why* it stopped being
    readable, and "the folder was removed on the 3rd" and "no folder ever
    covered this" are the same silence to a registry that deleted the row.

    Mount state is deliberately **not** stored. Whether the container can see
    the path depends on a bind mount and on whether a drive is plugged in;
    a stored value would go stale with nothing to correct it, and would report
    a USB disk as available an hour after it was unplugged.
    """

    __tablename__ = "roots"
    __table_args__ = (
        # Unique among the live ones only. A folder nominated, removed and
        # nominated again is a normal sequence — a plain unique constraint
        # would refuse the third step and blame the user for the second.
        Index(
            "uq_roots_path_active",
            "path",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    # As the user nominated it: absolute, normalised, symlinks unresolved. It
    # is the same string the native directory picker returns in M7 and the same
    # one the source viewer shows, so resolving it here would display a path
    # the user never typed.
    path: Mapped[str] = mapped_column(Text, nullable=False)

    # What was carrying the path at registration, when it could be told. Null
    # means unknown, never "local" — the only thing it drives is the network
    # share warning, and inventing a value to avoid an empty field is a claim
    # nothing checked.
    filesystem: Mapped[str | None] = mapped_column(String(64))

    added_at: Mapped[datetime] = created_at()

    # Tombstone. Not a delete — see the class docstring.
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- sources and their contents ---------------------------------------------


class Source(Base):
    """A folder, spreadsheet, dump or live connection the user added."""

    __tablename__ = "sources"
    __table_args__ = (
        _one_of("kind", SOURCE_KINDS, "kind"),
        _one_of("status", SOURCE_STATUSES, "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    # Where the material is. Askwell indexes in place rather than copying, so
    # this is the user's own directory, not a managed store. It must lie under
    # a nominated `roots` row; a path no root covers is never read.
    root_path: Mapped[str | None] = mapped_column(Text)

    # Encrypted with a key derived from the optional passphrase plus a
    # per-install secret, so a copied disk is not a credential leak (C8).
    config_encrypted: Mapped[bytes | None] = mapped_column()

    # C3: an imported dump is untrusted code and loads only into the isolated
    # sandbox Postgres, one database per source. This names that database.
    sandbox_db: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'queued'"))
    # `ux/library.md`'s single "needs attention" expands to a specific cause and
    # a specific fix, which needs somewhere to put the cause.
    last_error: Mapped[str | None] = mapped_column(Text)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    added_at: Mapped[datetime] = created_at()


class Document(Base):
    """One file inside a source."""

    __tablename__ = "documents"
    __table_args__ = (
        _one_of("status", DOCUMENT_STATUSES, "status"),
        Index("ix_documents_source_id", "source_id"),
        Index("ix_documents_sha256", "sha256"),
        # One live version of a given content, per source. Created by the v1
        # migration in raw SQL and declared here so the two agree: without this
        # line the index exists in every database and in no model, and the next
        # `--autogenerate` run proposes *dropping* it.
        #
        # The application also checks — `askwell.sources.add` looks the hash up
        # across every live document, not just this source's — and the two are
        # not the same check. The code path recognises a duplicate so the user
        # is told which copy is indexed; the index makes storing one impossible
        # when a later code path forgets to ask. A rule with one enforcement
        # point lapses silently, because nothing looks wrong about two rows.
        #
        # Partial, over the live rows only. A file deleted and added again is an
        # ordinary sequence, and so is a superseded version — a plain unique
        # constraint would refuse both and blame the user for the earlier step.
        Index(
            "uq_documents_live_source_id_sha256",
            "source_id",
            "sha256",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND superseded_by IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)

    # The path the file was found at, kept because Askwell indexes in place.
    # A moved or renamed file is therefore not an edge case, it is the normal
    # consequence of that choice — and without the original path there is no
    # way to tell moved from deleted. `ux/source-viewer.md` §4 requires that
    # distinction, because treating a moved file as deleted is both wrong and
    # alarming.
    path: Mapped[str] = mapped_column(Text, nullable=False)
    missing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    mime: Mapped[str | None] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)

    # Versions. NOT deletion — see the module docstring.
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )

    # Deletion. NOT supersession. The row survives so old citations resolve to
    # "deleted on <date>"; the chunk content and embedding are cleared so the
    # document stops influencing retrieval.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_reason: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'queued'"))

    # A poor scan is flagged in the library, shown beside the image in the
    # source viewer, and can raise a clarification.
    ocr_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    added_at: Mapped[datetime] = created_at()


class DocumentPage(Base):
    """One page's text, as extraction left it. `M1-EXTRACT-ING-026`.

    A row exists for every page, whether or not extraction found text on it —
    `has_text = false` is the record the OCR ticket reads to know which pages
    it owns, and a page silently skipped here would be a page OCR never learns
    it needs to look at. Chunking (`M1-INDEX-ING-031`) reads this table rather
    than re-parsing the file, which is also what lets extraction and chunking
    be different jobs.
    """

    __tablename__ = "document_pages"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "page_number", name="uq_document_pages_document_id_page_number"
        ),
        Index("ix_document_pages_document_id", "document_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    has_text: Mapped[bool] = mapped_column(Boolean, nullable=False)
    added_at: Mapped[datetime] = created_at()


class IngestJob(Base):
    """One document's place in the ingestion queue, and how far it has got.

    The queue is durable because the reason it exists is that somebody added
    five hundred papers and closed their laptop. Redis carries the *dispatch* —
    `arq` is what wakes a worker — but a job that exists only in Redis is a job
    that a `podman compose down -v`, a crash mid-run or a failed enqueue loses
    silently. This table is the record; the queue is the transport, and the two
    are reconciled rather than trusted to agree (`askwell.ingest`).

    One row per document, not one per attempt. A retry increments `attempts`
    and clears `error` rather than accumulating history: what the library has to
    render is "this file failed, here is why, retry" — and a per-attempt table
    would be a growing log nothing reads to answer that question.

    `seq` rather than `enqueued_at` for ordering. Two documents from one drop
    are enqueued inside the same transaction and share a timestamp to the
    microsecond, so a timestamp cannot order them and a queue position computed
    from one would jump about between reads.
    """

    __tablename__ = "ingest_jobs"
    __table_args__ = (
        _one_of("state", INGEST_STATES, "state"),
        # One live job per document. A second row would be a second worker
        # extracting the same file into the same chunks.
        UniqueConstraint("document_id", name="uq_ingest_jobs_document_id"),
        # The dispatcher's query: the next queued job in order. Partial,
        # because the finished rows are the ones that accumulate and none of
        # them is ever the answer.
        Index(
            "ix_ingest_jobs_pending",
            "seq",
            postgresql_where=text("state IN ('queued', 'running')"),
        ),
        Index("ix_ingest_jobs_source_id", "source_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    # Ordering. `Identity` rather than a Python-side counter for the same
    # reason every default here is a server default: a row inserted by a repair
    # script or a `psql` session must get one too.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalised from the document deliberately. Every read of this table is
    # "how far has this source got", and a join per poll — twice a second, for
    # as long as an import runs — buys nothing on a laptop that is also running
    # a model.
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )

    state: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'queued'"))
    # The last stage that completed, and the first stage that has not been
    # built. `awaiting` is what turns "nothing is happening to my files" into a
    # sentence naming what has to arrive first.
    stage: Mapped[str | None] = mapped_column(String(32))
    awaiting: Mapped[str | None] = mapped_column(String(32))

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)

    # Progress *inside* one file, so a single enormous PDF does not look hung.
    # Nullable rather than zero: "no stage has said how big this is" and "none
    # of it is done" are different facts, and a progress bar rendered from the
    # second when the first is true is the untimed spinner this ticket exists
    # to remove.
    bytes_done: Mapped[int | None] = mapped_column(BigInteger)
    bytes_total: Mapped[int | None] = mapped_column(BigInteger)

    enqueued_at: Mapped[datetime] = created_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Chunk(Base):
    """A retrievable passage.

    `content_tsv` is a generated column rather than something the application
    maintains: a trigger or an application write can be forgotten, and a stale
    search index is invisible until someone cannot find a document they know
    they added. Its expression (`c7e2f814a5b3`) replaces hyphens with spaces
    before tokenising, so a reference number like `INV-2024-0917` indexes as
    three independent, signless lexemes rather than the parser reading each
    `-<digits>` run as a negative number and burying the sign in the lexeme.
    """

    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(Text)

    # Nullable because deletion clears it. The row stays for citations.
    content: Mapped[str | None] = mapped_column(Text)
    content_tsv: Mapped[str | None] = mapped_column(TSVECTOR)

    # Dimension comes from configuration, never a literal here. Changing the
    # embedding model is a configuration change plus a re-embed, not a schema
    # edit — the migration reads it.
    embedding: Mapped[Any | None] = mapped_column(Vector())


class SchemaNote(Base):
    """What a table or column in a user's database actually means.

    `origin` is the honesty signal the interface renders in `--inferred`: an
    ochre-marked description means "I guessed this — correct me", and that is
    what drives the clarification loop.
    """

    __tablename__ = "schema_notes"
    __table_args__ = (
        _one_of("origin", NOTE_ORIGINS, "origin"),
        Index("ix_schema_notes_source_id", "source_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    column_name: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))

    # User-supplied notes outrank inferred ones and are never silently
    # overwritten. A correction supersedes; it does not update in place.
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schema_notes.id", ondelete="SET NULL")
    )
    embedding: Mapped[Any | None] = mapped_column(Vector())
    created_at_: Mapped[datetime] = mapped_column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# --- memory and clarification: the differentiator ---------------------------


class MemoryFact(Base):
    """Something Askwell knows because it asked, or was told.

    Named `MemoryFact` rather than `Memory` so the table name stays `memory`
    without the class reading like a module.
    """

    __tablename__ = "memory"
    __table_args__ = (_one_of("origin", MEMORY_ORIGINS, "origin"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    fact: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memory.id", ondelete="SET NULL")
    )
    created_at_: Mapped[datetime] = mapped_column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Clarification(Base):
    """A question Askwell wants to ask about a source.

    `rank` is stored, not computed on read. The cap is five per source with a
    documented ranking, so which questions made the cut — and which were
    inferred instead — is a fact about what happened, not something to
    re-derive later under different weights.
    """

    __tablename__ = "clarifications"
    __table_args__ = (
        _one_of("status", CLARIFICATION_STATUSES, "status"),
        Index("ix_clarifications_source_id", "source_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # The value distribution shown beside the question. It is what makes the
    # question answerable in seconds rather than an exam.
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    rank: Mapped[int | None] = mapped_column(Integer)
    answer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'pending'")
    )
    asked_at: Mapped[datetime] = created_at()
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- conversations ----------------------------------------------------------


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        _one_of("mode", CONVERSATION_MODES, "mode"),
        _one_of("ai_backend", AI_BACKENDS, "ai_backend"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'text'"))

    # Which backend answered. Recorded per conversation because online AI is a
    # deliberate per-conversation opt-in and never sticky (C1).
    ai_backend: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'local'")
    )
    created_at_: Mapped[datetime] = mapped_column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Message(Base):
    """One turn.

    `trace` holds the step sequence the trace screen renders and nothing that
    belongs in a real table. Traces rotate; citations and fact usage do not, so
    an old answer keeps its sources long after its debugging detail is gone.
    """

    __tablename__ = "messages"
    __table_args__ = (
        _one_of("role", MESSAGE_ROLES, "role"),
        Index("ix_messages_conversation_id", "conversation_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    trace: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at_: Mapped[datetime] = mapped_column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Citation(Base):
    """A claim in an answer, and the passage it came from.

    A real table rather than a field in `messages.trace`, because C4 is a
    constraint and a constraint that cannot be queried cannot be enforced or
    measured. "Did any answer contain an uncited claim?" has to be answerable.

    The foreign key to `chunks` is deliberately NOT cascade-delete. A deleted
    document's chunk row survives precisely so the citation still resolves.
    """

    __tablename__ = "citations"
    __table_args__ = (
        Index("ix_citations_message_id", "message_id"),
        Index("ix_citations_chunk_id", "chunk_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chunks.id"), nullable=False)
    claim_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    quoted_span: Mapped[str | None] = mapped_column(Text)


class FactUsage(Base):
    """Which remembered facts an answer used.

    A join table rather than a counter on `memory`, because a counter does not
    survive a deletion and cannot answer "which answers used this?". A wrong
    belief used once is a nuisance; used in forty answers it has been
    corrupting results for weeks, and that is the number that makes the memory
    screen worth opening.
    """

    __tablename__ = "fact_usage"
    __table_args__ = (
        _one_of("fact_kind", FACT_KINDS, "fact_kind"),
        Index("ix_fact_usage_message_id", "message_id"),
        Index("ix_fact_usage_fact_id", "fact_id"),
        UniqueConstraint("message_id", "fact_kind", "fact_id", name="message_id_fact_kind_fact_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    # Polymorphic by kind rather than two nullable foreign keys: the two fact
    # tables are unrelated and a row referencing both, or neither, is
    # meaningless.
    fact_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    fact_id: Mapped[uuid.UUID] = mapped_column(nullable=False)


# --- audit ------------------------------------------------------------------
# Two tables, not one, on purpose: different retention and different
# write-failure behaviour. C6 — append-only and tamper-evident. Not immutable:
# the user owns the machine and can always delete a file. The honest guarantee
# is that the application never rewrites history and that manual tampering is
# detectable.


class _AuditBase:
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # The chain. `prev_hash` is null only for the first record in the table.
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), nullable=False)


class AuditDecision(_AuditBase, Base):
    """Decisions the user made: what was added, deleted, corrected, confirmed."""

    __tablename__ = "audit_decisions"
    __table_args__ = (Index("ix_audit_decisions_occurred_at", "occurred_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    occurred_at: Mapped[datetime] = created_at()


class AuditInteraction(_AuditBase, Base):
    """What was asked and answered. Higher volume, shorter retention."""

    __tablename__ = "audit_interactions"
    __table_args__ = (Index("ix_audit_interactions_occurred_at", "occurred_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    occurred_at: Mapped[datetime] = created_at()
