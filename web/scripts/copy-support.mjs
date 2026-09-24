/**
 * Copies the repository's own `SUPPORT.md` and `SECURITY.md` into `public/`
 * so Settings → About can open the support boundary and the security route
 * with no network — the same one-canonical-source reasoning
 * `copy-notices.mjs` applies to `NOTICES.md`. `M7-DOC-DOC-164`.
 *
 * Written as `.txt`, not `.md`: the interface server picks a content type
 * from the extension, `.md` goes out as `text/markdown`, and a browser may
 * offer that as a download instead of showing it. `text/plain` is always
 * shown, and both files read fine as plain text.
 *
 *   node scripts/copy-support.mjs
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, "..");
const ROOT = join(WEB, "..");

const COPIES = [
  ["SUPPORT.md", "support.txt"],
  ["SECURITY.md", "security-policy.txt"],
];

mkdirSync(join(WEB, "public"), { recursive: true });
for (const [from, to] of COPIES) {
  const source = join(ROOT, from);
  if (!existsSync(source)) {
    console.error(`copy-support.mjs: ${source} does not exist.`);
    process.exit(1);
  }
  writeFileSync(join(WEB, "public", to), readFileSync(source, "utf8"));
  console.log(`copy-support.mjs: public/${to} written from ${from}`);
}
