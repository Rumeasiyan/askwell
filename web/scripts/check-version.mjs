/**
 * The frontend must report the repository's version, not its own copy of it.
 *
 * `AGENTS.md` §7: one manually maintained version value, at the repository
 * root. A `version` field in package.json is a second hand-maintained copy,
 * and a second copy is how a build ships a number that matches nothing — the
 * kind of mismatch nobody notices until a bug report names a version that was
 * never released.
 *
 *   node scripts/check-version.mjs
 */

import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, "..");
const ROOT = join(WEB, "..");

const problems = [];

const version = readFileSync(join(ROOT, "VERSION"), "utf8").trim();

if (!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(version)) {
  problems.push(
    `VERSION is ${version === "" ? "empty" : `"${version}"`}. The format is ` +
      `MAJOR.MINOR.PATCH and has no fourth component — a hotfix is a PATCH ` +
      `release, not 1.4.2.1.`,
  );
}

const manifest = JSON.parse(readFileSync(join(WEB, "package.json"), "utf8"));
if ("version" in manifest) {
  problems.push(
    `web/package.json declares version "${manifest.version}". It must not: ` +
      `the version comes from the repository's VERSION file, read by ` +
      `next.config.ts at build time. Two hand-maintained copies drift, and ` +
      `the build keeps working while reporting the wrong one.`,
  );
}

const config = readFileSync(join(WEB, "next.config.ts"), "utf8");
if (!config.includes('"VERSION"')) {
  problems.push(
    `next.config.ts no longer reads the VERSION file. The interface would ` +
      `then report whatever was last baked in, which is worse than reporting ` +
      `nothing.`,
  );
}

// Only when a build exists: the default `check` runs before one does.
const built = join(WEB, "out", "index.html");
if (existsSync(built)) {
  const html = readFileSync(built, "utf8");
  if (!html.includes(version)) {
    problems.push(
      `The built output does not contain ${version}. Either the build is ` +
        `stale, or the version stopped reaching the interface.`,
    );
  }
}

if (problems.length > 0) {
  console.error("Version discipline (AGENTS.md §7):\n");
  for (const problem of problems) console.error(`  · ${problem}\n`);
  process.exit(1);
}

console.log(`Version ${version}, from the repository's VERSION file and nowhere else.`);
