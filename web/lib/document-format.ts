/**
 * Which of the source viewer's renderers a document's own `mime` belongs to.
 * `M1-VIEW-FE-047`.
 *
 * Mirrors `askwell.extract.run`'s dispatch on the API side, kept as its own
 * lookup rather than inferred from `anchor_kind` — `anchor_kind` is a display
 * label written once extraction succeeds, so a document that has never been
 * extracted (or whose extractor failed) still needs a category to route on.
 */

const CONVERTED_TEXT_MIMES = new Set([
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "text/html",
  "text/markdown",
  "text/plain",
]);

const SPREADSHEET_MIMES = new Set([
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
]);

export type DocumentFormat = "pdf" | "converted-text" | "spreadsheet" | "unsupported";

export function documentFormat(mime: string | null): DocumentFormat {
  if (mime === "application/pdf") return "pdf";
  if (mime !== null && CONVERTED_TEXT_MIMES.has(mime)) return "converted-text";
  if (mime !== null && SPREADSHEET_MIMES.has(mime)) return "spreadsheet";
  return "unsupported";
}
