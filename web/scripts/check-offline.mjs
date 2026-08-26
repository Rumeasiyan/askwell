/**
 * Scan the built output for anything that would reach the network.
 *
 * C1 is the constraint the whole product rests on: disconnect the machine and
 * Askwell must work identically. The target user cannot upload their material
 * at all, so a single unexpected runtime URL breaks the only promise that makes
 * the product usable to them.
 *
 * This checks the built output rather than the source, deliberately. Intent
 * lives in the source; what actually ships lives in `out/`. A font import
 * pulled in by a dependency is invisible in the first and obvious in the second.
 *
 * It also checks *context* rather than matching URLs. A bundled dependency
 * contains dozens of URL strings that are never requested — core-js probes the
 * URL parser with `new URL("https://a#б")`, React and Next embed documentation
 * links into error messages. A flat allow-list cannot tell those from
 * `fetch("https://...")`, so it grows until it hides the thing it was added to
 * catch. Instead: a URL in a fetching position fails; a URL in a string
 * literal is reported as inert and counted, so a jump in that count is
 * visible in review.
 *
 *   node scripts/check-offline.mjs            report, exit non-zero on failure
 *   node scripts/check-offline.mjs --verbose  also list every inert reference
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "..", "out");

const TEXTUAL = new Set([".html", ".css", ".js", ".mjs", ".json", ".map", ".svg", ".txt", ".xml"]);
const FONTS = new Set([".woff", ".woff2", ".ttf", ".otf", ".eot"]);

/** A host that is not this machine. */
const EXTERNAL_HOST = String.raw`(?!localhost|127\.0\.0\.1|\[::1\])[a-z0-9-]+(?:\.[a-z0-9-]+)+`;

/**
 * Positions that actually cause a request. Each of these is a hard failure
 * wherever it names a host that is not this machine.
 */
const FETCHING = [
  {
    name: "markup asset reference",
    files: [".html", ".svg"],
    regex: new RegExp(
      String.raw`\b(?:src|href|action|formaction|data|poster|srcset|xlink:href)\s*=\s*["'](?:https?:)?//` +
        EXTERNAL_HOST,
      "gi",
    ),
  },
  {
    // A resource hint is only a problem when it points somewhere else. Next
    // preloads its own chunks by root-relative path on every page, and failing
    // that would mean the check can never pass — a check nobody can satisfy
    // gets disabled, which is worse than not having one.
    name: "resource hint to an external host",
    files: [".html"],
    regex: new RegExp(
      String.raw`<link\b[^>]*\brel=["'](?:preconnect|dns-prefetch|prefetch|preload|modulepreload)["'][^>]*\bhref=["'](?:https?:)?//` +
        EXTERNAL_HOST,
      "gi",
    ),
  },
  {
    // href before rel. Attribute order is not guaranteed and a check that only
    // handles one order is a check with a hole in it.
    name: "resource hint to an external host",
    files: [".html"],
    regex: new RegExp(
      String.raw`<link\b[^>]*\bhref=["'](?:https?:)?//` +
        EXTERNAL_HOST +
        String.raw`[^>]*\brel=["'](?:preconnect|dns-prefetch|prefetch|preload|modulepreload)["']`,
      "gi",
    ),
  },
  {
    name: "stylesheet import from a host",
    files: [".css", ".html"],
    regex: new RegExp(String.raw`@import\s+(?:url\()?\s*["']?(?:https?:)?//` + EXTERNAL_HOST, "gi"),
  },
  {
    name: "stylesheet url() from a host",
    files: [".css", ".html"],
    regex: new RegExp(String.raw`url\(\s*["']?(?:https?:)?//` + EXTERNAL_HOST, "gi"),
  },
  {
    name: "runtime request",
    files: [".js", ".mjs", ".html"],
    // fetch("https://…"), new Worker("//…"), sendBeacon('https://…'), and the
    // rest of the shapes that take a URL and go and get it.
    regex: new RegExp(
      String.raw`\b(?:fetch|importScripts|sendBeacon|open)\s*\(\s*["'\`](?:https?:)?//` +
        EXTERNAL_HOST +
        String.raw`|new\s+(?:Worker|SharedWorker|WebSocket|EventSource|Image|Audio)\s*\(\s*["'\`](?:wss?:|https?:)?//` +
        EXTERNAL_HOST,
      "gi",
    ),
  },
  {
    name: "websocket URL",
    files: [".js", ".mjs", ".html", ".json"],
    regex: new RegExp(String.raw`\bwss?://` + EXTERNAL_HOST, "gi"),
  },
];

/** Any host-shaped string, for the inert count. */
const ANY_URL = new RegExp(String.raw`\bhttps?://` + EXTERNAL_HOST + String.raw`[^\s"'\`)>\\]*`, "gi");

function walk(directory) {
  const found = [];
  for (const entry of readdirSync(directory)) {
    const full = join(directory, entry);
    if (statSync(full).isDirectory()) found.push(...walk(full));
    else found.push(full);
  }
  return found;
}

let files;
try {
  files = walk(OUT);
} catch {
  console.error(`No built output at ${OUT}. Run the build first: pnpm build`);
  process.exit(1);
}

const failures = [];
const inert = new Map();

for (const file of files) {
  const extension = extname(file);
  if (!TEXTUAL.has(extension)) continue;
  const content = readFileSync(file, "utf8");
  const where = relative(OUT, file);

  for (const { name, files: applies, regex } of FETCHING) {
    if (!applies.includes(extension)) continue;
    for (const hit of content.matchAll(regex)) {
      failures.push({ where, name, text: hit[0].slice(0, 140) });
    }
  }

  for (const hit of content.matchAll(ANY_URL)) {
    const url = hit[0];
    inert.set(url, (inert.get(url) ?? 0) + 1);
  }
}

const bundledFonts = files.filter((f) => FONTS.has(extname(f)));

if (failures.length > 0) {
  console.error(`${failures.length} reference(s) that would reach the network:\n`);
  for (const f of failures) console.error(`  ${f.where}\n    ${f.name}: ${f.text}\n`);
  console.error(
    "C1: disconnect the machine and Askwell must work identically.\n" +
      "This is not a lint warning. Remove the reference or bundle the asset.",
  );
  process.exit(1);
}

console.log(`No fetching reference to an external host in ${files.length} built files.`);
console.log(
  bundledFonts.length === 0
    ? "No font files bundled — the type stack is system faces only, as intended (§3)."
    : `${bundledFonts.length} bundled font file(s), served from the output itself.`,
);

const total = [...inert.values()].reduce((a, b) => a + b, 0);
console.log(
  `\n${inert.size} distinct host-shaped string(s) appear in the bundle (${total} occurrences),\n` +
    `none of them in a fetching position. These are URL-parser probes and\n` +
    `documentation links inside error messages. Run with --verbose to list them;\n` +
    `a jump in this count is worth looking at in review.`,
);

if (process.argv.includes("--verbose")) {
  for (const [url, count] of [...inert].sort()) {
    console.log(`  ${String(count).padStart(3)}x  ${url.slice(0, 100)}`);
  }
}
