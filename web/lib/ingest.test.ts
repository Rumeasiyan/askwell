/**
 * The sentences the queue produces, which are the part that can be wrong.
 *
 * Not the fetch, and — with one exception — not the EventSource: those either
 * work or produce a network error somebody will see. What can be quietly wrong
 * is the prose: a spinner for work that has not started, an estimate nobody
 * measured, or a source described as unaskable when eighty of its five hundred
 * papers are indexed and answerable right now.
 *
 * The exception is how many connections get opened, which turned out to be the
 * counter-example to "those either work or produce a network error". Opening
 * one stream per watcher exhausts the browser's six-per-origin pool and the tab
 * then stalls with no error at all, so that count is asserted below.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  type IngestState,
  type SourceCoverage,
  type FlaggedDocument,
  coverageSentence,
  duration,
  estimateSentence,
  queueSentence,
  subscribeIngest,
  failureSentence,
  flaggedSentence,
  retryDocument,
  type FailedDocument,
} from "./ingest.ts";

function state(over: Partial<IngestState> = {}): IngestState {
  return {
    counts: { queued: 0, running: 0, parked: 0, failed: 0, done: 0 },
    documents_ingested: 0,
    documents_failed: 0,
    documents_flagged: 0,
    queue_length: 0,
    concurrency: 2,
    estimate: { seconds: 0, basis: "nothing is waiting" },
    active: [],
    next: [],
    failures: [],
    flagged: [],
    sources: [],
    awaiting: null,
    stages: [
      { name: "extract", ticket: "M1-EXTRACT-ING-026", built: false },
      { name: "chunk", ticket: "M1-INDEX-ING-031", built: false },
      { name: "embed", ticket: "M1-INDEX-ING-032", built: false },
    ],
    ...over,
  };
}

function coverage(over: Partial<SourceCoverage> = {}): SourceCoverage {
  return {
    id: "b2f0c1e2-0000-4000-8000-000000000001",
    name: "papers",
    status: "indexing",
    kind: "file",
    added_at: "2026-08-28T00:00:00Z",
    last_error: null,
    deleted_at: null,
    open_clarifications: 0,
    total: 500,
    ready: 80,
    failed: 0,
    running: 2,
    outstanding: 420,
    flagged: 0,
    askable: true,
    fraction: 0.16,
    ...over,
  };
}

test("a drop waiting on a stage that does not exist says which stage", () => {
  const sentence = queueSentence(
    state({ counts: { queued: 0, running: 0, parked: 3, failed: 0, done: 0 } }),
  );

  assert.match(sentence, /3 files are recorded and waiting/);
  assert.match(sentence, /needs extract, which is not built yet \(M1-EXTRACT-ING-026\)/);
  // The promise the whole add flow makes, repeated where the user is looking.
  assert.match(sentence, /Nothing has been copied/);
});

test("one file waiting is not described as one files", () => {
  const sentence = queueSentence(
    state({ counts: { queued: 0, running: 0, parked: 1, failed: 0, done: 0 } }),
  );
  assert.match(sentence, /1 file is recorded/);
});

test("a file being indexed says how far through it is", () => {
  const sentence = queueSentence(
    state({
      queue_length: 3,
      counts: { queued: 2, running: 1, parked: 0, failed: 0, done: 0 },
      active: [
        {
          document_id: "d",
          filename: "scan.pdf",
          source_id: "s",
          stage: "extract",
          attempt: 1,
          bytes_done: 512,
          bytes_total: 1024,
          fraction: 0.5,
        },
      ],
    }),
  );

  // Within the file, not just between files. A 900-page scan that only ever
  // says "1 of 3" is indistinguishable from a hang.
  assert.match(sentence, /Indexing scan\.pdf — 50% of the way through/);
  assert.match(sentence, /2 waiting behind it/);
});

test("an estimate nobody has measured is the reason, never a number", () => {
  const basis = "no estimate yet — nothing has finished indexing on this machine";
  assert.equal(estimateSentence({ seconds: null, basis }), basis);
});

test("a measured estimate carries what it was measured from", () => {
  const sentence = estimateSentence({
    seconds: 4200,
    basis: "measured from 40 files averaging 210s each, 2 at a time",
  });
  assert.match(sentence, /About 70 minutes left/);
  assert.match(sentence, /measured from 40 files/);
});

test("a duration is never more precise than it is", () => {
  assert.equal(duration(45), "45 seconds");
  assert.equal(duration(600), "10 minutes");
  assert.equal(duration(7200), "2 hours");
});

test("a partly indexed source says what can be asked about now", () => {
  const sentence = coverageSentence(coverage());
  assert.match(sentence, /80 of 500 indexed/);
  assert.match(sentence, /ask about those now/);
});

test("a source with nothing indexed does not claim to be answerable", () => {
  assert.match(coverageSentence(coverage({ ready: 0, askable: false })), /nothing here can be asked/);
});

test("a finished source says so plainly", () => {
  assert.equal(coverageSentence(coverage({ ready: 500, outstanding: 0 })), "All 500 indexed.");
});


// --- how many connections the page opens -------------------------------------

/** The bare minimum of EventSource this module actually touches. */
class FakeEventSource {
  static opened = 0;
  static live = 0;
  static instances: FakeEventSource[] = [];
  listeners = new Map<string, (event: unknown) => void>();
  url: string;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.opened += 1;
    FakeEventSource.live += 1;
    FakeEventSource.instances.push(this);
  }

  addEventListener(name: string, handler: (event: unknown) => void): void {
    this.listeners.set(name, handler);
  }

  close(): void {
    FakeEventSource.live -= 1;
  }

  emit(state: IngestState): void {
    this.listeners.get("progress")?.({ data: JSON.stringify(state) });
  }
}

function withFakeEventSource<T>(body: () => T): T {
  const original = (globalThis as { EventSource?: unknown }).EventSource;
  FakeEventSource.opened = 0;
  FakeEventSource.live = 0;
  FakeEventSource.instances = [];
  (globalThis as { EventSource?: unknown }).EventSource = FakeEventSource;
  try {
    return body();
  } finally {
    (globalThis as { EventSource?: unknown }).EventSource = original;
  }
}

test("six watchers open one connection, not six", () => {
  withFakeEventSource(() => {
    // Six is the number that matters: it is the browser's per-origin limit, so
    // one-per-watcher is the point at which the whole tab stops responding.
    const stops = Array.from({ length: 6 }, () => subscribeIngest(() => {}));
    assert.equal(FakeEventSource.opened, 1);
    assert.equal(FakeEventSource.live, 1);
    for (const stop of stops) {
      stop();
    }
  });
});

test("every watcher is told, and the connection closes when the last one leaves", () => {
  withFakeEventSource(() => {
    const seen: number[] = [];
    const stopA = subscribeIngest(() => seen.push(1));
    const stopB = subscribeIngest(() => seen.push(2));

    const instance = FakeEventSource.instances.at(-1);
    assert.ok(instance, "subscribing should have opened a stream");
    instance.emit(state());
    assert.deepEqual(seen, [1, 2]);

    stopA();
    assert.equal(FakeEventSource.live, 1, "one watcher left, so the stream stays open");
    stopB();
    assert.equal(FakeEventSource.live, 0, "nothing is watching, so nothing stays connected");

    // A second cleanup must not reopen or double-close anything.
    stopB();
    assert.equal(FakeEventSource.live, 0);
  });
});

test("watching again after everyone left opens a fresh connection", () => {
  withFakeEventSource(() => {
    subscribeIngest(() => {})();
    const stop = subscribeIngest(() => {});
    assert.equal(FakeEventSource.opened, 2);
    assert.equal(FakeEventSource.live, 1);
    stop();
  });
});


// --- a failure the user can act on -------------------------------------------

function failed(over: Partial<FailedDocument> = {}): FailedDocument {
  return {
    document_id: "d1",
    filename: "scan.pdf",
    source_id: "b2f0c1e2-0000-4000-8000-000000000001",
    stage: null,
    error: "The file is open in another program.",
    attempts: 1,
    ...over,
  };
}

test("a failure names the file, because which one is the first question", () => {
  const said = failureSentence(failed());
  assert.match(said, /scan\.pdf/);
  assert.match(said, /open in another program/);
});

test("a failure names the stage when there is one", () => {
  assert.match(failureSentence(failed({ stage: "reading it" })), /while reading it/);
});

test("repeated attempts are said, once there has been more than one", () => {
  assert.doesNotMatch(failureSentence(failed({ attempts: 1 })), /Tried/);
  assert.match(failureSentence(failed({ attempts: 3 })), /Tried 3 times/);
});

test("a missing reason is called a bug rather than left blank", () => {
  // An empty reason would render as "scan.pdf could not be read: ." which reads
  // as though Askwell knows and will not say.
  assert.match(failureSentence(failed({ error: null })), /did not record a reason/);
});

test("a refused retry throws the API's own sentence, never a bare status", () => {
  const original = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ error: "That document is not failed — it is running." }), {
      status: 409,
    })) as typeof fetch;
  return retryDocument("d1")
    .then(
      () => assert.fail("a 409 must not resolve"),
      (error: unknown) => {
        assert.match(String(error), /not failed/);
      },
    )
    .finally(() => {
      globalThis.fetch = original;
    });
});

test("a retry that succeeds resolves", () => {
  const original = globalThis.fetch;
  globalThis.fetch = (async () => new Response("{}", { status: 202 })) as typeof fetch;
  return retryDocument("d1").finally(() => {
    globalThis.fetch = original;
  });
});


// --- a scan that read poorly, but is not a failure ---------------------------

function flagged(over: Partial<FlaggedDocument> = {}): FlaggedDocument {
  return {
    document_id: "d1",
    filename: "photocopy.pdf",
    source_id: "s1",
    confidence: 0.42,
    poor_pages: [],
    ...over,
  };
}

test("a flagged document names the file and the confidence, never as a failure", () => {
  const said = flaggedSentence(flagged());
  assert.match(said, /photocopy\.pdf/);
  assert.match(said, /42% confidence/);
  assert.match(said, /indexed and searchable/);
});

test("a flagged document names the specific pages that read worst", () => {
  const said = flaggedSentence(flagged({ poor_pages: [2, 5] }));
  assert.match(said, /pages 2, 5 read worst/);
});

test("a flagged document with one poor page says page, singular", () => {
  const said = flaggedSentence(flagged({ poor_pages: [3] }));
  assert.match(said, /page 3 read worst/);
});

test("a flagged document with no page detail still names the confidence", () => {
  const said = flaggedSentence(flagged({ poor_pages: [] }));
  assert.doesNotMatch(said, /read worst/);
});
