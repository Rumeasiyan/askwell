// Capture every screenshot in docs/manual/screenshots from the demo stack.
// docs/manual/AUTHORING.md. Run through `scripts/dev.sh manual-shots`.
//
// The demo stack (scripts/manual/demo-stack.sh) starts empty, with the
// fictional Meridian Loom documents in a demo home folder and no model, so the
// first screens are what a new install shows. Nothing here can capture the
// development database or anyone's real files.

import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { launchChrome, openPage } from "./cdp.mjs";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const OUT = join(REPO, "docs/manual/screenshots");
const PORT = process.env.ASKWELL_MANUAL_PORT ?? "8010";
const BASE = `http://127.0.0.1:${PORT}`;
const HOME = process.env.ASKWELL_MANUAL_HOME ?? "/tmp/anna";
const FOLDER = `${HOME}/Documents/Meridian Loom`;
const WIDTH = 1280;

const NOT_IN_FILES = "What is the company's policy on bringing pets to the office?";

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const say = (text) => console.log(`\x1b[36m==>\x1b[0m ${text}`);

function demo(command, env = {}) {
  execFileSync(join(REPO, "scripts/manual/demo-stack.sh"), [command], {
    stdio: "inherit",
    env: { ...process.env, ...env },
  });
}

const js = (value) => JSON.stringify(value);

async function capture(page, name, clip) {
  const { data } = await page.send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: true,
    clip: { scale: 1, ...clip },
  });
  writeFileSync(join(OUT, name), Buffer.from(data, "base64"));
  say(`screenshots/${name}`);
}

/** The top of the window, down to `height`. */
const top = (page, name, height) => capture(page, name, { x: 0, y: 0, width: WIDTH, height });

/** The region from the element holding `fromText` to the one holding
 * `toText`, across the main column, with a margin. The main column scrolls
 * on its own, so the region is scrolled into view and taken from the window. */
async function between(page, name, fromText, toText, margin = 16) {
  const box = await page.evaluate(`(() => {
    const find = (t) => [...document.querySelectorAll("main *")].filter((e) =>
      [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.includes(t)));
    const a = find(${js(fromText)})[0], b = find(${js(toText)}).at(-1);
    if (!a || !b) return null;
    a.scrollIntoView({ block: "start" });
    const main = document.querySelector("main").getBoundingClientRect();
    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    return { x: main.left, y: ra.top, width: main.width, height: rb.bottom - ra.top };
  })()`);
  if (box === null) throw new Error(`could not find "${fromText}" … "${toText}" on the page`);
  await sleep(300);
  const y = Math.max(0, box.y - margin);
  await capture(page, name, {
    x: box.x,
    y,
    width: box.width,
    height: Math.min(800 - y, box.height + margin * 2),
  });
}

async function click(page, text, selector = "button") {
  const done = await page.evaluate(`(() => {
    const e = [...document.querySelectorAll(${js(selector)})].find((x) => x.textContent.trim().startsWith(${js(text)}));
    if (!e) return false;
    e.click();
    return true;
  })()`);
  if (!done) throw new Error(`no ${selector} labelled "${text}"`);
}

const hasText = (text) => `document.body.textContent.includes(${js(text)})`;
const stopShown = `[...document.querySelectorAll("button")].some((b) => b.textContent.trim() === "Stop")`;

async function ask(page, question) {
  await page.goto(`${BASE}/`);
  await page.waitFor(`document.querySelector("textarea")`);
  await page.evaluate(`(() => {
    const e = document.querySelector("textarea");
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(e, ${js(question)});
    e.dispatchEvent(new Event("input", { bubbles: true }));
  })()`);
  await page.evaluate(`document.querySelector("button.ask-action-primary").click()`);
  await page.waitFor(stopShown, { timeoutMs: 60000, label: "the answer to start" });
  await page.waitFor(`!(${stopShown})`, { timeoutMs: 600000, label: "the answer to finish" });
  await sleep(1500);
  if (await page.evaluate(hasText("Which is current?"))) {
    throw new Error(`"${question}" stopped on a clarification; the screenshot would not show an answer`);
  }
}

async function main() {
  mkdirSync(OUT, { recursive: true });

  say("demo stack, as a new install: empty, no model");
  demo("down");
  demo("up", { ASKWELL_MANUAL_MODEL: "missing" });

  const browser = await launchChrome({ width: WIDTH, height: 800 });
  let page = null;
  try {
    page = await openPage(browser, { width: WIDTH, height: 800 });
    await page.goto(`${BASE}/`);
    await page.evaluate(`localStorage.setItem("askwell-theme", "light")`);
    // A standard laptop, whatever this machine measured: the profile most
    // readers have, through the same call Settings → Change profile makes.
    await page.evaluate(`fetch("/probe/override", { method: "POST", headers: { "content-type": "application/json" }, body: ${js(JSON.stringify({ tier: "standard" }))} }).then((r) => r.status)`);

    await page.goto(`${BASE}/`);
    await page.waitFor(hasText("Get started"));
    await top(page, "welcome.png", 440);

    await click(page, "Get started");
    await page.waitFor(hasText("Check the machine"));
    await sleep(1000);
    await click(page, "Continue");
    await page.waitFor(hasText("I already have the file"), { label: "the Download step" });
    await sleep(1000);
    await top(page, "welcome-model.png", 370);

    say("the model is in place");
    demo("model");

    // A new user adds their first folder from the welcome steps, where the
    // Add a source panel sits under the model, now ready.
    await page.goto(`${BASE}/`);
    await page.waitFor(hasText("Get started"));
    await click(page, "Get started");
    await page.waitFor(hasText("Check the machine"));
    await sleep(800);
    await click(page, "Continue");
    await page.waitFor(hasText("Ready."), { label: "the model to be ready" });
    await page.waitFor(`document.querySelector("input[type=file][webkitdirectory]")`);
    const { root } = await page.send("DOM.getDocument", { depth: -1 });
    const { nodeId } = await page.send("DOM.querySelector", {
      nodeId: root.nodeId,
      selector: "input[type=file][webkitdirectory]",
    });
    await page.send("DOM.setFileInputFiles", { nodeId, files: [FOLDER] });
    await page.waitFor(hasText("Which folder is"), { label: "the folder question" });
    await page.evaluate(`(() => {
      const e = document.querySelector("input[id^=folder-]");
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(e, ${js(`${HOME}/Documents`)});
      e.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    await click(page, "Add them");
    await page.waitFor(hasText("has not been given this folder yet"), { label: "the Nominate prompt" });
    await sleep(800);
    await between(page, "add-nominate.png", "From 1 folder", "Nominate ");
    await click(page, "Nominate ");
    await page.waitFor(`!(${hasText("has not been given this folder yet")})`, {
      label: "the folder to be nominated and the files added",
    });
    await sleep(3000);

    say("indexing");
    await page.goto(`${BASE}/library/`);
    await page.waitFor(hasText("All 9 indexed"), { timeoutMs: 900000, label: "indexing to finish" });
    await sleep(1000);
    await top(page, "library.png", 320);

    await page.goto(`${BASE}/clarifications/`);
    await page.waitFor(hasText("Which is current?"), { timeoutMs: 300000, label: "a clarification" });
    await sleep(1000);
    await top(page, "clarifications.png", 420);

    await page.goto(`${BASE}/memory/`);
    await page.waitFor(hasText("Confirm"), { timeoutMs: 120000, label: "a memory entry" });
    await sleep(1000);
    await top(page, "memory.png", 500);

    // No screenshot of an ordinary answer until #919 is fixed: the default
    // model's answers currently carry stray lines that would teach readers
    // the wrong thing about what an answer looks like.
    say("asking");
    await ask(page, NOT_IN_FILES);
    if (!(await page.evaluate(hasText("Nothing in your files answers this.")))) {
      throw new Error(`"${NOT_IN_FILES}" was answered; pick a question the demo files do not cover`);
    }
    await top(page, "abstain.png", 445);
    page.close();
  } catch (error) {
    // What the page showed when a step failed, for whoever runs this next.
    // Outside docs/: it is not an illustration.
    if (page !== null) {
      const failure = join(REPO, ".run/manual-shots-failure.png");
      writeFileSync(failure, await page.screenshot());
      console.error(`the page at the failure: ${failure}`);
    }
    throw error;
  } finally {
    await browser.close();
    say("removing the demo stack");
    demo("down");
  }
}

await main();
