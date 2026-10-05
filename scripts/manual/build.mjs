// Build the Askwell user manual: docs/manual/chapters -> askwell-manual.html
// (committed, so its history shows what readers were given) and, with --pdf,
// docs/manual/build/askwell-manual.pdf (not committed). docs/manual/AUTHORING.md.
//
//   node scripts/manual/build.mjs          the HTML only
//   node scripts/manual/build.mjs --pdf    the HTML, then the PDF through headless Chrome

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { launchChrome, openPage } from "./cdp.mjs";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const MANUAL = join(REPO, "docs/manual");
const OUT_HTML = join(MANUAL, "askwell-manual.html");
const OUT_PDF = join(MANUAL, "build/askwell-manual.pdf");

const escape = (text) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function buildHtml() {
  const manifest = JSON.parse(readFileSync(join(MANUAL, "manifest.json"), "utf8"));
  const css = readFileSync(join(MANUAL, "manual.css"), "utf8").trim();
  const contents = manifest.chapters
    .map((chapter) => `      <li><a href="#ch-${chapter.id}">${escape(chapter.title)}</a></li>`)
    .join("\n");
  // Each chapter is copied in unchanged, so the committed file shows exactly
  // the source a reader got, and api/tests/test_manual.py can tell when a
  // chapter changed without a rebuild.
  const sections = manifest.chapters
    .map((chapter) => {
      const body = readFileSync(join(MANUAL, "chapters", chapter.file), "utf8").trim();
      return `<section class="chapter" id="ch-${chapter.id}">\n${body}\n</section>`;
    })
    .join("\n\n");
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escape(manifest.title)}</title>
<!-- Built by scripts/manual/build.mjs from docs/manual/chapters. Do not edit by hand. -->
<style>
${css}
</style>
</head>
<body>
<header class="cover">
  <h1>Askwell</h1>
  <p>User manual. A personal AI over your own files, on your own computer.</p>
</header>
<nav class="contents" aria-label="Contents">
  <ol>
${contents}
  </ol>
</nav>

${sections}
</body>
</html>
`;
}

async function buildPdf() {
  const browser = await launchChrome();
  try {
    const page = await openPage(browser);
    await page.goto(pathToFileURL(OUT_HTML).href);
    await page.evaluate("document.fonts.ready.then(() => true)");
    const pdf = await page.pdf({
      printBackground: true,
      preferCSSPageSize: true,
      displayHeaderFooter: true,
      headerTemplate: "<span></span>",
      footerTemplate:
        '<div style="width:100%;font-size:8px;color:#5f655e;text-align:center;font-family:monospace">' +
        'Askwell user manual · <span class="pageNumber"></span></div>',
    });
    mkdirSync(dirname(OUT_PDF), { recursive: true });
    writeFileSync(OUT_PDF, pdf);
    page.close();
  } finally {
    await browser.close();
  }
}

writeFileSync(OUT_HTML, buildHtml());
console.log(`wrote ${OUT_HTML.slice(REPO.length + 1)}`);
if (process.argv.includes("--pdf")) {
  await buildPdf();
  console.log(`wrote ${OUT_PDF.slice(REPO.length + 1)}`);
}
