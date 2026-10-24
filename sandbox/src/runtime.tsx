// The lesson runtime: runs inside the sandboxed iframe (and, identically, in the render check). It receives
// `{type: "render", code, data, codeVersion, theme}`, transforms the generated TSX with sucrase, evaluates it with the
// scope, and reports `rendered`, `error` and `height` to the page that embeds it.

import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { transform } from "sucrase";

import { SCOPE_NAMES, STANDARD_NAMES } from "./scope-names.mjs";
import { SCOPE } from "./scope";
import { describeError, post, setCodeVersion } from "./scope/host";
import { Boundary } from "./scope/shell";

const STANDARD = new Set<string>(STANDARD_NAMES);
let root: Root | null = null;
let currentVersion = 0;

function reportError(phase: "transform" | "runtime", error: unknown, extra: Record<string, unknown> = {}) {
  post({ type: "error", phase, codeVersion: currentVersion, ...describeError(error), ...extra });
}

window.addEventListener("error", (event) => reportError("runtime", event.error ?? event.message));
window.addEventListener("unhandledrejection", (event) => reportError("runtime", event.reason));

function applyTheme(theme?: string) {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

function mount(element: React.ReactElement) {
  const container = document.getElementById("root")!;
  root ??= createRoot(container);
  root.render(
    <Boundary name="LessonDocument">
      <React.StrictMode>{element}</React.StrictMode>
    </Boundary>,
  );
}

function run(code: string, data: unknown) {
  const lesson = data as { pages?: Record<string, { sections?: { id: string }[] }> };
  (globalThis as unknown as { __LESSON__: unknown }).__LESSON__ = lesson;
  let js: string;
  try {
    js = transform(code, { transforms: ["typescript", "jsx"], jsxRuntime: "classic", production: true }).code;
  } catch (error) {
    reportError("transform", error);
    return;
  }
  const scope: Record<string, unknown> = { ...SCOPE, LESSON: lesson, render: mount };
  const names = Object.keys(scope);
  try {
    new Function(...names, js)(...names.map((name) => scope[name]));
  } catch (error) {
    reportError("runtime", error);
    return;
  }
  requestAnimationFrame(() => {
    post({ type: "rendered", codeVersion: currentVersion, height: document.documentElement.scrollHeight });
  });
}

window.addEventListener("message", (event: MessageEvent) => {
  const message = event.data;
  if (!message || typeof message !== "object") return;
  if (message.type === "render") {
    currentVersion = Number(message.codeVersion ?? 0);
    setCodeVersion(currentVersion);
    applyTheme(message.theme);
    run(String(message.code ?? ""), message.data);
  } else if (message.type === "theme") {
    applyTheme(message.theme);
  }
});

new ResizeObserver(() => post({ type: "height", height: document.documentElement.scrollHeight })).observe(document.body);

// A check that every name the checker allows is provided here (a mismatch would be a lesson that passes the check
// and then crashes). Reported once, at start-up, so the render check and the tests see it.
const missing = [...SCOPE_NAMES].filter((name) => !(name in SCOPE) && name !== "LESSON" && name !== "render" && !STANDARD.has(name));
if (missing.length) post({ type: "error", phase: "runtime", message: `The runtime lacks scope names: ${missing.join(", ")}`, stack: "" });
post({ type: "ready" });
