#!/usr/bin/env node
// Renders an assembled lesson document in headless Chromium, with the SAME runtime the browser uses, and reports what
// broke. Reads one JSON request on stdin, writes one JSON report on stdout (exit 0 ok, 1 problems).
//
//   {"code", "data", "pages": ["introduction", …], "mediaFiles": {assetId: path}, "pageTimeoutMs"}
//     → {"ok", "pages": {key: [errors]}, "components": {name: [errors]}, "security": [violations]}
//
// Each page is checked in a fresh browser context: it must render without uncaught errors, error-boundary hits or
// console errors; survive clicking up to eight buttons and moving every range input; finish within the time budget
// (an infinite loop is caught here); not be blank; and make no network request except to the local runtime and the
// lesson's own media. Anything else is blocked and reported as a security violation.

import { readFileSync } from "node:fs";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");
const ORIGIN = "https://sandbox.invalid";
const MEDIA_ORIGIN = "https://media.invalid";
const MIME = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp" };
const MAX_CLICKS = 8;

const request = JSON.parse(readFileSync(0, "utf8"));
const pageTimeoutMs = request.pageTimeoutMs ?? 8000;

function harnessHtml() {
  return readFileSync(join(dist, "harness.html"), "utf8")
    .replaceAll("__ASSETS__", ORIGIN)
    .replaceAll("__MEDIA__", MEDIA_ORIGIN)
    .replace("__RUNTIME_CSS__", `${ORIGIN}/runtime.css`)
    .replace("__TAILWIND__", `${ORIGIN}/tailwind.js`)
    .replace("__RUNTIME__", `${ORIGIN}/runtime.js`);
}

const ASSETS = { "/runtime.js": "application/javascript", "/runtime.css": "text/css", "/tailwind.js": "application/javascript" };

async function checkPage(browser, key, report) {
  const errors = [];
  const consoleErrors = [];
  const events = [];
  const context = await browser.newContext({ serviceWorkers: "block", viewport: { width: 900, height: 1200 } });
  const page = await context.newPage();
  const note = (message) => errors.push(message);

  await page.exposeFunction("__lessonHost", (message) => events.push(message));
  page.on("pageerror", (error) => note(`Uncaught error: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    if (/Content Security Policy|Refused to/i.test(text)) report.security.push(`Blocked by the CSP: ${text.slice(0, 200)}`);
    else consoleErrors.push(text);
  });
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin === ORIGIN) {
      if (url.pathname === "/index.html") return route.fulfill({ contentType: "text/html", body: harnessHtml() });
      if (ASSETS[url.pathname]) return route.fulfill({ contentType: ASSETS[url.pathname], body: readFileSync(join(dist, url.pathname.slice(1))) });
    }
    if (url.origin === MEDIA_ORIGIN) {
      const file = request.mediaFiles?.[url.pathname.slice(1)];
      if (file) return route.fulfill({ contentType: MIME[extname(file).toLowerCase()] ?? "application/octet-stream", body: readFileSync(file) });
    }
    report.security.push(`Blocked request: ${route.request().method()} ${url.href.slice(0, 200)}`);
    return route.abort("blockedbyclient");
  });

  const work = async () => {
    await page.goto(`${ORIGIN}/index.html`, { waitUntil: "load" });
    for (let waited = 0; !events.some((e) => e.type === "ready") && waited < 5000; waited += 50) await page.waitForTimeout(50);
    await page.evaluate((message) => window.postMessage(message, "*"), {
      type: "render", code: request.code, data: request.data, codeVersion: 1, theme: "light",
    });
    await page.waitForFunction(() => typeof window.__goto === "function", null, { timeout: 5000 }).catch(() => note("The document did not render."));
    await page.evaluate((k) => window.__goto?.(k), key);
    await page.waitForTimeout(500);

    const main = page.locator(`main[data-page="${key}"]`);
    if ((await main.count()) === 0) {
      note(`The ${key} page did not render.`);
      return;
    }
    const buttons = main.locator("button");
    const count = Math.min(await buttons.count(), MAX_CLICKS);
    for (let i = 0; i < count; i++) {
      await buttons.nth(i).click({ timeout: 1500, force: true }).catch(() => {});
      await page.waitForTimeout(80);
    }
    await main.locator('input[type="range"]').evaluateAll((inputs) => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      for (const input of inputs) {
        const span = Number(input.max || 100) - Number(input.min || 0);
        for (const fraction of [0.25, 0.75, 1]) {
          setter.call(input, String(Number(input.min || 0) + span * fraction));
          input.dispatchEvent(new Event("input", { bubbles: true }));
          input.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }
    });
    await page.waitForTimeout(300);

    const { text, headings } = await main.evaluate((el) => ({
      text: el.innerText.trim().length,
      headings: [...el.querySelectorAll("h1,h2,h3")].reduce((n, h) => n + h.innerText.length, 0),
    }));
    if (text < 40 || text < headings) note(`The ${key} page is blank or nearly so.`);
  };

  let timer;
  const timedOut = new Promise((resolveTimeout) => {
    timer = setTimeout(() => resolveTimeout("timeout"), pageTimeoutMs);
  });
  try {
    const outcome = await Promise.race([work().then(() => "done"), timedOut]);
    if (outcome === "timeout") note(`The ${key} page did not finish in ${pageTimeoutMs} ms (an endless loop or runaway timer?).`);
  } catch (error) {
    note(`The ${key} page could not be checked: ${String(error.message).split("\n")[0]}`);
  } finally {
    clearTimeout(timer);
  }

  // React logs an error it caught in a boundary to the console too; the boundary already reported it by name.
  const reported = events.filter((e) => e.type === "error").map((e) => e.message);
  for (const text of consoleErrors) {
    if (!reported.some((message) => message && text.includes(message))) note(`console.error: ${text.slice(0, 300)}`);
  }
  for (const event of events) {
    if (event.type !== "error") continue;
    const message = `${event.phase === "transform" ? "Syntax" : "Runtime"} error: ${event.message}`;
    if (event.component && event.component.startsWith("Interactive_")) {
      (report.components[event.component] ??= []).push(message);
    } else {
      note(message);
    }
  }
  await Promise.race([context.close(), new Promise((r) => setTimeout(r, 3000))]).catch(() => {});
  return [...new Set(errors)];
}

const report = { ok: true, pages: {}, components: {}, security: [] };
const browser = await chromium.launch({ headless: true, args: ["--no-sandbox", "--disable-dev-shm-usage"] });
try {
  for (const key of request.pages) report.pages[key] = await checkPage(browser, key, report);
} finally {
  await Promise.race([browser.close(), new Promise((r) => setTimeout(r, 5000))]).catch(() => {});
}
report.security = [...new Set(report.security)];
report.ok =
  report.security.length === 0 &&
  Object.values(report.pages).every((e) => e.length === 0) &&
  Object.values(report.components).every((e) => e.length === 0);
process.stdout.write(JSON.stringify(report));
process.exit(report.ok ? 0 : 1);
