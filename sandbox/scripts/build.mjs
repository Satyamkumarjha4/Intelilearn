#!/usr/bin/env node
// Builds the lesson runtime: dist/runtime.js (+ runtime.css), the Tailwind browser build, and the harness HTML
// template. The browser (frontend/public/sandbox) and the render check load these same files. With OUT set, the
// result is also copied there.

import { copyFileSync, cpSync, existsSync, mkdirSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import * as esbuild from "esbuild";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");
mkdirSync(dist, { recursive: true });

// KaTeX lists each font as woff2, woff and ttf; browsers use the first they support, so only woff2 is embedded.
const katexWoff2Only = {
  name: "katex-woff2-only",
  setup(build) {
    build.onLoad({ filter: /katex[\\/].*\.css$/ }, (args) => ({
      contents: readFileSync(args.path, "utf8").replace(/,\s*url\([^)]*\.(?:woff|ttf)\)\s*format\("(?:woff|truetype)"\)/g, ""),
      loader: "css",
      resolveDir: dirname(args.path),
    }));
  },
};

await esbuild.build({
  plugins: [katexWoff2Only],
  entryPoints: [join(root, "src/runtime.tsx")],
  outfile: join(dist, "runtime.js"),
  bundle: true,
  format: "iife",
  jsx: "transform",
  minify: true,
  target: "es2020",
  loader: { ".woff2": "dataurl", ".woff": "dataurl", ".ttf": "dataurl" },
  define: { "process.env.NODE_ENV": '"production"' },
  logLevel: "warning",
});
copyFileSync(join(root, "node_modules/@tailwindcss/browser/dist/index.global.js"), join(dist, "tailwind.js"));
copyFileSync(join(root, "src/harness.html"), join(dist, "harness.html"));

if (process.env.OUT) {
  mkdirSync(process.env.OUT, { recursive: true });
  for (const file of readdirSync(dist)) cpSync(join(dist, file), join(process.env.OUT, file));
}
console.log(`sandbox built: ${readdirSync(dist).join(", ")}${process.env.OUT && existsSync(process.env.OUT) ? ` → ${process.env.OUT}` : ""}`);
