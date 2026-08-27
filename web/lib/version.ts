/**
 * The running version.
 *
 * Baked in at build time from the repository's VERSION file — see
 * next.config.ts. There is exactly one place this number is written down, and
 * this is not it.
 */
export const VERSION: string = process.env.NEXT_PUBLIC_ASKWELL_VERSION ?? "unknown";
