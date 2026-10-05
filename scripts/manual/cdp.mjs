// A minimal Chrome DevTools Protocol client for the manual's screenshots and
// PDF. No dependencies: Node 22 has `fetch` and `WebSocket` built in, and the
// browser is the Chrome already on the machine. See docs/manual/AUTHORING.md.

import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME_CANDIDATES = [
  process.env.ASKWELL_MANUAL_CHROME,
  "google-chrome",
  "google-chrome-stable",
  "chromium",
  "chromium-browser",
].filter(Boolean);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForEndpoint(port, child) {
  for (let i = 0; i < 100; i++) {
    if (child.exitCode !== null) throw new Error(`Chrome exited with code ${child.exitCode}`);
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (response.ok) return;
    } catch {
      // not listening yet
    }
    await sleep(100);
  }
  throw new Error("Chrome did not open its debugging port");
}

export async function launchChrome({ width = 1280, height = 800 } = {}) {
  const profile = mkdtempSync(join(tmpdir(), "askwell-manual-chrome-"));
  const port = 9300 + Math.floor(Math.random() * 500);
  let lastError;
  for (const binary of CHROME_CANDIDATES) {
    const child = spawn(
      binary,
      [
        "--headless=new",
        `--remote-debugging-port=${port}`,
        `--user-data-dir=${profile}`,
        `--window-size=${width},${height}`,
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--hide-scrollbars",
        "about:blank",
      ],
      { stdio: "ignore" },
    );
    const failed = new Promise((resolve) => child.once("error", resolve));
    const outcome = await Promise.race([
      waitForEndpoint(port, child).then(() => null, (error) => error),
      failed,
    ]);
    if (outcome === null) {
      return {
        port,
        async close() {
          child.kill();
          await sleep(200);
          rmSync(profile, { recursive: true, force: true });
        },
      };
    }
    lastError = outcome;
    child.kill();
  }
  rmSync(profile, { recursive: true, force: true });
  throw new Error(
    `No Chrome could be started (tried ${CHROME_CANDIDATES.join(", ")}): ${lastError?.message ?? lastError}. ` +
      "Set ASKWELL_MANUAL_CHROME to the browser's path.",
  );
}

/** One page target, driven over its WebSocket. */
export async function openPage(browser, { width = 1280, height = 800 } = {}) {
  const response = await fetch(`http://127.0.0.1:${browser.port}/json/new?about:blank`, {
    method: "PUT",
  });
  const target = await response.json();
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = reject;
  });
  let nextId = 1;
  const pending = new Map();
  const listeners = new Set();
  socket.onmessage = (message) => {
    const data = JSON.parse(message.data);
    if (data.id && pending.has(data.id)) {
      const { resolve, reject } = pending.get(data.id);
      pending.delete(data.id);
      if (data.error) reject(new Error(`${data.error.message} ${data.error.data ?? ""}`));
      else resolve(data.result);
    } else if (data.method) {
      for (const listener of listeners) listener(data);
    }
  };
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject });
      socket.send(JSON.stringify({ id, method, params }));
    });

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: false,
  });

  const page = {
    send,
    async goto(url) {
      const loaded = new Promise((resolve) => {
        const listener = (event) => {
          if (event.method === "Page.loadEventFired") {
            listeners.delete(listener);
            resolve();
          }
        };
        listeners.add(listener);
      });
      await send("Page.navigate", { url });
      await loaded;
    },
    async evaluate(expression) {
      const result = await send("Runtime.evaluate", {
        expression,
        awaitPromise: true,
        returnByValue: true,
      });
      if (result.exceptionDetails) {
        throw new Error(result.exceptionDetails.exception?.description ?? "evaluation failed");
      }
      return result.result.value;
    },
    /** Waits until `expression` is truthy in the page. */
    async waitFor(expression, { timeoutMs = 30000, label = expression } = {}) {
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        if (await page.evaluate(`Boolean(${expression})`)) return;
        await sleep(250);
      }
      throw new Error(`Timed out waiting for: ${label}`);
    },
    async screenshot() {
      const { data } = await send("Page.captureScreenshot", { format: "png" });
      return Buffer.from(data, "base64");
    },
    async pdf(options) {
      const { data } = await send("Page.printToPDF", options);
      return Buffer.from(data, "base64");
    },
    close() {
      socket.close();
    },
  };
  return page;
}
