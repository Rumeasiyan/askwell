import assert from "node:assert/strict";
import { test } from "node:test";

import { controlShowing, trapTab } from "./drawer.ts";

// Five destinations plus the drawer's own close control.
const COUNT = 6;

test("Tab off the last control wraps to the first", () => {
  assert.equal(trapTab(COUNT, COUNT - 1, false), 0);
});

test("Shift+Tab off the first control wraps to the last", () => {
  assert.equal(trapTab(COUNT, 0, true), COUNT - 1);
});

test("a move that stays inside is left to the browser", () => {
  assert.equal(trapTab(COUNT, 2, false), null);
  assert.equal(trapTab(COUNT, 2, true), null);
  assert.equal(trapTab(COUNT, 0, false), null);
  assert.equal(trapTab(COUNT, COUNT - 1, true), null);
});

test("focus outside the drawer is pulled back in at the end the key points to", () => {
  assert.equal(trapTab(COUNT, -1, false), 0);
  assert.equal(trapTab(COUNT, -1, true), COUNT - 1);
});

test("a single control keeps focus on itself both ways", () => {
  assert.equal(trapTab(1, 0, false), 0);
  assert.equal(trapTab(1, 0, true), 0);
});

test("nothing focusable is not an error", () => {
  assert.equal(trapTab(0, -1, false), null);
});

test("the control counts as showing only while it has a box", () => {
  assert.equal(controlShowing({ width: 30, height: 26 }), true);
  // `display: none` under `@3xl:hidden` — the window was widened past the
  // breakpoint, so the drawer must resolve into the column.
  assert.equal(controlShowing({ width: 0, height: 0 }), false);
  assert.equal(controlShowing(undefined), false);
});
