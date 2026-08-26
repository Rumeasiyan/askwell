import type { NextConfig } from "next";

const config: NextConfig = {
  // Static assets on disk, served by the API (M0-FOUND-DEPLOY-004). There is
  // no permanent Node process on the user's machine: no server to keep alive,
  // no session to protect, no search index to serve.
  output: "export",

  // Next's image optimiser is a server. Without this the export fails, and
  // "just add a loader" would mean an external image service — which C1
  // forbids outright.
  images: { unoptimized: true },

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
