import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { NextConfig } from "next";

/**
 * The version, read from the repository's VERSION file at build time.
 *
 * AGENTS.md §7 makes that file the single source. A `version` field in
 * package.json would be a second hand-maintained copy, and a second copy is
 * how a build ships a number that matches nothing — so package.json
 * deliberately has none, and a test asserts it stays that way.
 *
 * Read here rather than at runtime because a static export has no runtime to
 * read a file in.
 */
const version = readFileSync(join(import.meta.dirname, "..", "VERSION"), "utf8").trim();

const config: NextConfig = {
  // Static assets on disk, served by the API (M0-FOUND-DEPLOY-004). There is
  // no permanent Node process on the user's machine: no server to keep alive,
  // no session to protect, no search index to serve.
  output: "export",

  // Next's image optimiser is a server. Without this the export fails, and
  // "just add a loader" would mean an external image service — which C1
  // forbids outright.
  images: { unoptimized: true },

  // Exposed to the browser so the About screen can render it rather than
  // repeat it (docs/ux/settings.md §7).
  env: { NEXT_PUBLIC_ASKWELL_VERSION: version },

  // Directory-style URLs, so the API can serve `out/` as plain files without
  // a rewrite rule per route.
  trailingSlash: true,

  // A build that reports success while `tsc` is failing is worse than no check
  // at all. There is no matching `eslint` key: Next 16 removed `next lint`, so
  // linting is its own step (`pnpm lint`), run by scripts/dev.sh alongside the
  // build rather than inside it.
  typescript: { ignoreBuildErrors: false },
};

export default config;
