/**
 * Settings → Model and speed's copy and figures. `M7-SET-FE-146`.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  PROFILE_EXPECTATIONS,
  formatBytes,
  memoryLine,
  noCandidates,
  sourceLabel,
  swapConsequence,
  swapInProgress,
  throughputLines,
  type ModelState,
} from "./model.ts";

const base: ModelState = {
  source: "shipped",
  display_name: "Qwen3.5 4B (Q4_K_M)",
  state: "ready",
  reason: null,
  loaded_file: "Qwen3.5-4B-Q4_K_M.gguf",
  memory_bytes: 4_698_161_152,
  acceleration: "cpu",
  file_bytes: 2_740_000_000,
  throughput: { turns: 0, tokens_per_second: null, prompt_tokens_per_second: null, median_answer_ms: null },
  models_dir: "~/.local/share/askwell/models",
  candidates: [],
  unverified_statement: "x",
  swap_timeout_seconds: 300,
};

test("throughput before any question says so rather than showing zero", () => {
  const lines = throughputLines(base.throughput);
  assert.equal(lines.length, 1);
  assert.match(lines.join(" "), /Not measured yet/);
  assert.doesNotMatch(lines.join(" "), /\b0(\.0)? tokens/);
});

test("measured throughput shows the real numbers and how many answers they cover", () => {
  const lines = throughputLines({
    turns: 2,
    tokens_per_second: 8.84,
    prompt_tokens_per_second: 41.2,
    median_answer_ms: 85_000,
  }).join(" ");
  assert.match(lines, /85 seconds/);
  assert.match(lines, /8\.8 tokens per second/);
  assert.match(lines, /41 tokens per second/);
  assert.match(lines, /last 2 answers/);
});

test("memory is the measured figure, or says why it is absent", () => {
  assert.match(memoryLine(base), /4\.4 GB of memory in use by the model, measured/);
  assert.match(memoryLine({ ...base, memory_bytes: null, state: "starting" }), /not running/);
  assert.match(memoryLine({ ...base, memory_bytes: null }), /Not measured on this machine/);
  assert.doesNotMatch(memoryLine({ ...base, memory_bytes: null }), /\b0 (GB|MB)/);
  // On a graphics card, resident memory omits the offloaded weights (issue 674).
  assert.doesNotMatch(memoryLine(base), /graphics card/);
  const gpu = memoryLine({ ...base, acceleration: "gpu" });
  assert.match(gpu, /4\.4 GB of system memory/);
  assert.match(gpu, /graphics card is not included/);
});

test("the swap consequence states unavailability, that search keeps working, and the restore", () => {
  const text = swapConsequence("Qwen3.5 4B (Q4_K_M)", 300);
  assert.match(text, /assistant is unavailable/);
  assert.match(text, /up to 5 minutes/);
  assert.match(text, /search, browsing and your library keep working/);
  assert.match(text, /goes back to Qwen3\.5 4B \(Q4_K_M\)/);
  assert.match(text, /decisions log/);
});

test("a swap in progress states the expected duration and that search keeps working", () => {
  const text = swapInProgress("my-own-model.gguf", 300);
  assert.match(text, /unavailable/);
  assert.match(text, /up to 5 minutes/);
  assert.match(text, /search and browsing still work/);
});

test("with no other model present, the folder to place one in is named", () => {
  const text = noCandidates("~/.local/share/askwell/models");
  assert.match(text, /~\/\.local\/share\/askwell\/models/);
  assert.match(text, /\.gguf/);
});

test("shipped reads as validated, user-supplied as unverified", () => {
  assert.equal(sourceLabel("shipped"), "Validated");
  assert.equal(sourceLabel("user_supplied"), "Unverified");
  assert.equal(sourceLabel("none"), "");
});

test("every profile has a plain-terms expectation", () => {
  for (const tier of ["light", "standard", "accelerated", "workstation"]) {
    assert.ok(PROFILE_EXPECTATIONS[tier]);
  }
});

test("sizes read in GB above a gigabyte", () => {
  assert.equal(formatBytes(3_013_027_808), "2.8 GB");
  assert.equal(formatBytes(50 * 1024 * 1024), "50 MB");
});
