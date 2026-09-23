/**
 * Copies the repository's own `NOTICES.md` into `public/` so the build
 * serves the one file that exists, rather than a second hand-maintained
 * copy that could drift from it (`AGENTS.md` §4's "one canonical source"
 * reasoning, applied here the same way `next.config.ts` applies it to
 * `VERSION`). `M7-DOC-DOC-163`.
 *
 *   node scripts/copy-notices.mjs
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, "..");
const ROOT = join(WEB, "..");

const source = join(ROOT, "NOTICES.md");
if (!existsSync(source)) {
  console.error(
    `copy-notices.mjs: ${source} does not exist. Run \`scripts/dev.sh notices\` to generate it first.`,
  );
  process.exit(1);
}

mkdirSync(join(WEB, "public"), { recursive: true });
writeFileSync(join(WEB, "public", "notices.md"), readFileSync(source, "utf8"));
console.log("copy-notices.mjs: public/notices.md written from NOTICES.md");
