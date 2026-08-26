/**
 * Token hygiene: colours and depth come from tokens, and only from tokens.
 *
 * The two rules here are the ones `docs/ux/design-system.md` singles out as
 * silent failures — defects that nobody reports, because nobody sees them.
 *
 * A literal shadow (`rgba(0,0,0,.07)`) reads as depth on paper and is
 * invisible on a dark ground, so it removes the affordance it was added for in
 * exactly one of the two themes. Whoever wrote it was almost certainly looking
 * at the other one.
 *
 * A literal colour is invisible to scripts/contrast.mjs, which only knows about
 * tokens. Every hardcoded hex is a pair that was never measured.
 *
 *   node scripts/check-tokens.mjs
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");

/** The one file allowed to contain literal colours: it is where they live. */
const TOKEN_DEFINITION = join(ROOT, "app", "globals.css");

const SOURCE_DIRS = ["app", "components", "lib"];
const SOURCE_EXT = new Set([".css", ".ts", ".tsx"]);

const LITERAL_COLOUR =
  /#[0-9a-fA-F]{3,8}\b|\brgba?\s*\([^)]*\)|\bhsla?\s*\([^)]*\)|\boklch\s*\([^)]*\)/g;

function walk(directory) {
  const found = [];
  for (const entry of readdirSync(directory)) {
    const full = join(directory, entry);
    if (statSync(full).isDirectory()) found.push(...walk(full));
    else if (SOURCE_EXT.has(extname(full))) found.push(full);
  }
  return found;
}

const problems = [];

// ---------------------------------------------------------------------------
// 1. No literal colour outside the token definition.
// ---------------------------------------------------------------------------
for (const directory of SOURCE_DIRS) {
  for (const file of walk(join(ROOT, directory))) {
    if (file === TOKEN_DEFINITION) continue;
    const content = readFileSync(file, "utf8");
    content.split("\n").forEach((line, index) => {
      for (const hit of line.matchAll(LITERAL_COLOUR)) {
        problems.push({
          file: relative(ROOT, file),
          line: index + 1,
          text: hit[0],
          why:
            "A literal colour is invisible to the contrast check, which only " +
            "knows about tokens. Use var(--token) or a token utility.",
        });
      }
    });
  }
}

// ---------------------------------------------------------------------------
// 2. Every shadow colour is a depth token.
// ---------------------------------------------------------------------------
const DEPTH_TOKENS = ["var(--inset)", "var(--drop)"];

for (const directory of SOURCE_DIRS) {
  for (const file of walk(join(ROOT, directory))) {
    const content = readFileSync(file, "utf8");
    const shadows = [
      ...content.matchAll(/box-shadow\s*:\s*([^;{}]+)[;}]/gi),
      ...content.matchAll(/boxShadow\s*:\s*["'`]([^"'`]+)["'`]/g),
    ];
    for (const [, value] of shadows) {
      if (value.trim() === "none") continue;
      if (!DEPTH_TOKENS.some((token) => value.includes(token))) {
        problems.push({
          file: relative(ROOT, file),
          line: content.slice(0, content.indexOf(value)).split("\n").length,
          text: `box-shadow: ${value.trim().slice(0, 70)}`,
          why:
            "Depth must come from --inset or --drop. Black at 7% reads as depth " +
            "on paper and is invisible on a dark ground, so a literal shadow " +
            "removes the affordance in exactly one theme.",
        });
      }
    }
  }
}

// ---------------------------------------------------------------------------
// 3. Both depth tokens differ between the themes.
// ---------------------------------------------------------------------------
const css = readFileSync(TOKEN_DEFINITION, "utf8");
function blockAfter(selector) {
  const start = css.indexOf(selector);
  if (start === -1) return "";
  const open = css.indexOf("{", start);
  return css.slice(open, css.indexOf("}", open));
}
const lightBlock = blockAfter(":root {");
const darkBlock = blockAfter(':root[data-theme="dark"]');

for (const token of ["inset", "drop"]) {
  const pattern = new RegExp(`--${token}:\\s*([^;]+);`);
  const light = lightBlock.match(pattern)?.[1]?.trim();
  const dark = darkBlock.match(pattern)?.[1]?.trim();
  if (!light || !dark) {
    problems.push({
      file: "app/globals.css",
      line: 0,
      text: `--${token}`,
      why: `Not defined in both themes. It is a depth token; it must differ per theme.`,
    });
  } else if (light === dark) {
    problems.push({
      file: "app/globals.css",
      line: 0,
      text: `--${token}: ${light}`,
      why:
        "Identical in both themes, which is the same defect as a literal " +
        "shadow: a value tuned for one ground does not carry on the other.",
    });
  }
}

if (problems.length > 0) {
  console.error(`${problems.length} token hygiene problem(s):\n`);
  for (const p of problems) {
    console.error(`  ${p.file}:${p.line}  ${p.text}\n    ${p.why}\n`);
  }
  process.exit(1);
}

console.log("Colours and depth come from tokens only.");
console.log(`  --inset  light ${lightBlock.match(/--inset:\s*([^;]+);/)?.[1]?.trim()}`);
console.log(`           dark  ${darkBlock.match(/--inset:\s*([^;]+);/)?.[1]?.trim()}`);
console.log(`  --drop   light ${lightBlock.match(/--drop:\s*([^;]+);/)?.[1]?.trim()}`);
console.log(`           dark  ${darkBlock.match(/--drop:\s*([^;]+);/)?.[1]?.trim()}`);
