/**
 * Measure contrast for every token pair the interface actually uses, in both
 * themes, and fail if any falls below its floor.
 *
 * This exists because the floors are not guessable. `docs/ux/design-system.md`
 * §8 records that `--muted` and `--inferred` originally failed on `--paper`
 * and `--sunk` in the *light* theme — the opposite of what everyone predicted.
 * A palette that looks fine is not evidence, so this reads the token values out
 * of app/globals.css and computes the ratios.
 *
 *   node scripts/contrast.mjs            report and exit non-zero on failure
 *   node scripts/contrast.mjs --markdown emit the table for the docs
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const CSS = readFileSync(join(HERE, "..", "app", "globals.css"), "utf8");

const TEXT_FLOOR = 4.5;
const UI_FLOOR = 3.0;

/** Token pairs the interface uses, and what each is used for. */
const PAIRS = [
  // Text: 4.5:1.
  ["ink", "paper", "text", "Answer prose, primary text"],
  ["ink", "surface", "text", "Text on a card or the margin rail"],
  ["ink", "sunk", "text", "Text typed into an input"],
  ["muted", "paper", "text", "Labels, metadata, timestamps"],
  ["muted", "surface", "text", "Metadata on a card"],
  ["muted", "sunk", "text", "Placeholder text in an input"],
  ["provenance", "paper", "text", "Citations, quoted passages"],
  ["provenance", "surface", "text", "Citation on a source card"],
  ["inferred", "paper", "text", "Anything Askwell guessed"],
  ["inferred", "surface", "text", "A guessed column description on a card"],
  ["alarm", "paper", "text", "Failure messages"],
  ["alarm", "surface", "text", "Failure state on a card"],
  ["paper", "ink", "text", "A filled primary action's label"],

  // UI lines and controls: 3:1.
  ["rule-strong", "paper", "ui", "The claim leader — the only thing joining a claim to its source"],
  ["rule-strong", "surface", "ui", "The inline source-card edge below the breakpoint"],
  ["provenance", "surface", "ui", "The source card's 2px left bar"],
  ["provenance", "paper", "ui", "The focus ring"],
  ["inferred", "paper", "ui", "The web-result dashed border (C10)"],
  ["ink", "paper", "ui", "A filled primary action against the ground"],
];

function themeBlock(selector) {
  const start = CSS.indexOf(selector);
  if (start === -1) throw new Error(`No block for ${selector} in globals.css`);
  const open = CSS.indexOf("{", start);
  const close = CSS.indexOf("}", open);
  return CSS.slice(open, close);
}

function tokensFrom(block) {
  const found = {};
  for (const [, name, value] of block.matchAll(/--([a-z-]+):\s*(#[0-9a-fA-F]{3,8})\s*;/g)) {
    found[name] = value;
  }
  return found;
}

// The light theme is the bare `:root` block; dark is the explicit override.
// The media-query block is deliberately not read: it holds the same values as
// `[data-theme="dark"]`, and reading the copy would hide a drift between them.
const LIGHT = tokensFrom(themeBlock(":root {"));
const DARK = { ...LIGHT, ...tokensFrom(themeBlock(':root[data-theme="dark"]')) };

function channel(value) {
  const c = value / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(hex) {
  const clean = hex.replace("#", "");
  const full =
    clean.length === 3
      ? clean
          .split("")
          .map((c) => c + c)
          .join("")
      : clean;
  const [r, g, b] = [0, 2, 4].map((i) => Number.parseInt(full.slice(i, i + 2), 16));
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function ratio(a, b) {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

const rows = [];
let failures = 0;

for (const [themeName, tokens] of [
  ["light", LIGHT],
  ["dark", DARK],
]) {
  for (const [fg, bg, kind, use] of PAIRS) {
    const foreground = tokens[fg];
    const background = tokens[bg];
    if (!foreground || !background) {
      console.error(`MISSING  ${themeName}  --${fg} on --${bg}: token not defined`);
      failures += 1;
      continue;
    }
    const floor = kind === "text" ? TEXT_FLOOR : UI_FLOOR;
    const measured = ratio(foreground, background);
    const passed = measured >= floor;
    if (!passed) failures += 1;
    rows.push({ themeName, fg, bg, kind, use, measured, floor, passed });
  }
}

// --rule-strong must not be --rule. It is the only thing joining a claim to
// its source, and collapsing the two is a silent, plausible simplification.
for (const [themeName, tokens] of [
  ["light", LIGHT],
  ["dark", DARK],
]) {
  if (tokens["rule-strong"] === tokens["rule"]) {
    console.error(
      `FAIL  ${themeName}  --rule-strong is identical to --rule. It carries meaning ` +
        `(the claim leader) and must reach 3:1 on its own.`,
    );
    failures += 1;
  }
}

if (process.argv.includes("--markdown")) {
  console.log("| Theme | Foreground | Background | Floor | Measured | Used for |");
  console.log("| ----- | ---------- | ---------- | ----- | -------- | -------- |");
  for (const r of rows) {
    console.log(
      `| ${r.themeName} | \`--${r.fg}\` | \`--${r.bg}\` | ${r.floor.toFixed(1)}:1 | ` +
        `**${r.measured.toFixed(2)}:1** | ${r.use} |`,
    );
  }
} else {
  for (const r of rows) {
    const mark = r.passed ? "pass" : "FAIL";
    console.log(
      `${mark}  ${r.themeName.padEnd(5)}  --${r.fg} on --${r.bg}`.padEnd(52) +
        `${r.measured.toFixed(2)}:1  (floor ${r.floor.toFixed(1)}:1)  ${r.use}`,
    );
  }
  const worst = rows.reduce((a, b) => (a.measured < b.measured ? a : b));
  console.log(
    `\n${rows.length} pairs measured across both themes. ` +
      `Tightest: --${worst.fg} on --${worst.bg} in ${worst.themeName} at ${worst.measured.toFixed(2)}:1.`,
  );
}

if (failures > 0) {
  console.error(`\n${failures} contrast failure(s). This is a build-blocking defect, not a design preference.`);
  process.exit(1);
}
