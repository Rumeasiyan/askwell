# Abstention

This governs the message shown when nothing retrieved from the user's own
documents or databases clears the retrieval threshold for a question. It is
composed directly from real counts and the nearest candidate's own heading —
no model call — but the rule below is the standing constraint that
composition path must never cross.

## The standing rule

General knowledge is never used to answer a question about the user's own
material. When retrieval finds nothing that clears the threshold, Askwell
says so plainly. It does not reach for what it knows in general and offer
that instead, even hedged, even labelled as uncertain, even "just in case it
helps". An uncited guess about the user's own files is worse than no answer
at all, because the user has no external source to check it against — that
is the whole of C5.

## What the message does, in order

1. **States the situation.** Nothing in your files answers this.
2. **Proves the search happened.** The real count of passages and sources
   searched, and the nearest material actually found — never invented, and
   never claimed when nothing at all was retrieved.
3. **Gives the next action.** Add the source you would expect this in.

## Never

Never apologise. Never hedge into a partial guess. Never offer a
general-knowledge answer "in case it helps". Never colour this as a
failure.

## The empty-corpus case is a different message

Nothing indexed at all is not the same situation as "searched and nothing
matched" — there is no search to prove happened and no nearest material to
name. Say that directly. Do not reuse the below-threshold wording with the
counts set to zero.
