#!/usr/bin/env node
// Static, security and scope checks for generated lesson code, and a LaTeX check. Reads one JSON request on stdin
// and writes one JSON reply on stdout; exit code 0 (ok) or 1 (problems found). The backend runs it in a subprocess
// (backend/graph/sandbox.py).
//
//   {"mode": "code", "code", "required": [names], "components": [names defined elsewhere], "assetIds": [ids]}
//     → {"ok", "errors": [{"line", "column", "rule", "message"}]}
//   {"mode": "latex", "items": [expressions]}
//     → {"ok", "errors": [{"item", "message"}]}

import { readFileSync } from "node:fs";

import { parse } from "@babel/parser";
import traverseModule from "@babel/traverse";
import * as esbuild from "esbuild";
import katex from "katex";

import { FORBIDDEN_ELEMENTS, FORBIDDEN_GLOBALS, FORBIDDEN_MEMBERS, SCOPE_NAMES } from "../src/scope-names.mjs";

const traverse = traverseModule.default ?? traverseModule;
const URL_PATTERN = /(?:https?:)?\/\/[\w.-]+\.[a-z]{2,}|\bhttps?:\/\/|\bjavascript:|\bdata:text\/html/i;

class Problems {
  list = [];
  add(rule, message, loc) {
    this.list.push({ line: loc?.line ?? 0, column: loc?.column ?? 0, rule, message });
  }
}

function syntaxProblems(code, problems) {
  try {
    esbuild.transformSync(code, { loader: "tsx", jsx: "transform", logLevel: "silent" });
  } catch (error) {
    for (const message of error.errors ?? [{ text: String(error.message), location: null }]) {
      problems.add("syntax", message.text, message.location && { line: message.location.line, column: message.location.column });
    }
    return false;
  }
  return true;
}

function tagName(nameNode) {
  if (nameNode.type === "JSXIdentifier") return nameNode.name;
  if (nameNode.type === "JSXMemberExpression") return tagName(nameNode.object);
  return "";
}

function securityProblems(ast, ctx, problems) {
  const { required, components, assetIds } = ctx;
  const allowed = new Set([...SCOPE_NAMES, ...components]);
  const declared = new Set();
  let usesSetInterval = false;
  let clearsInterval = false;

  traverse(ast, {
    ImportDeclaration: (p) => problems.add("no-import", "import is not allowed: everything you need is already in scope", p.node.loc?.start),
    ExportNamedDeclaration: (p) => problems.add("no-export", "export is not allowed", p.node.loc?.start),
    ExportDefaultDeclaration: (p) => problems.add("no-export", "export is not allowed", p.node.loc?.start),
    Import: (p) => problems.add("no-dynamic-import", "import() is not allowed", p.node.loc?.start),
    TSExportAssignment: (p) => problems.add("no-export", "export is not allowed", p.node.loc?.start),

    Program(path) {
      for (const [name, binding] of Object.entries(path.scope.bindings)) {
        if (["hoisted", "const", "let", "var"].includes(binding.kind)) declared.add(name);
      }
    },

    // Free identifiers: anything not declared in the code and not in scope.
    ReferencedIdentifier(path) {
      const { name } = path.node;
      if (path.scope.hasBinding(name, { noGlobals: true })) return;
      if (FORBIDDEN_GLOBALS.has(name)) {
        problems.add("forbidden-global", `\`${name}\` is not allowed in lesson code`, path.node.loc?.start);
      } else if (!allowed.has(name)) {
        problems.add("not-in-scope", `\`${name}\` is not defined: it is not in the sandbox scope and not declared in the code`, path.node.loc?.start);
      }
      if (name === "setInterval") usesSetInterval = true;
      if (name === "clearInterval") clearsInterval = true;
    },
    JSXIdentifier(path) {
      // <Foo /> components: an uppercase tag must be declared or in scope.
      if (!path.parentPath.isJSXOpeningElement({ name: path.node }) && !path.parentPath.isJSXMemberExpression()) return;
      const name = path.node.name;
      if (!/^[A-Z]/.test(name) || path.scope.hasBinding(name, { noGlobals: true })) return;
      if (path.parentPath.isJSXMemberExpression() && path.parentPath.node.property === path.node) return;
      if (!allowed.has(name)) {
        problems.add("not-in-scope", `<${name}> is not defined: it is not in the sandbox scope and not declared in the code`, path.node.loc?.start);
      }
    },

    MemberExpression(path) {
      const { property, computed } = path.node;
      const key = computed ? (property.type === "StringLiteral" ? property.value : null) : property.name;
      if (key && FORBIDDEN_MEMBERS.has(key)) {
        problems.add("forbidden-member", `\`.${key}\` is not allowed (it reaches outside the sandbox)`, path.node.loc?.start);
      }
      if (computed && property.type !== "StringLiteral" && property.type !== "NumericLiteral" && property.type !== "Identifier") {
        // obj[expr()]: allowed; only literal keys can be checked statically
      }
    },
    OptionalMemberExpression(path) {
      const { property, computed } = path.node;
      const key = computed ? (property.type === "StringLiteral" ? property.value : null) : property.name;
      if (key && FORBIDDEN_MEMBERS.has(key)) problems.add("forbidden-member", `\`.${key}\` is not allowed`, path.node.loc?.start);
    },

    JSXOpeningElement(path) {
      const name = tagName(path.node.name);
      if (name && FORBIDDEN_ELEMENTS.has(name)) {
        const hint = ["img", "image", "video", "audio", "source"].includes(name) ? "; use <Figure asset=…> for media" : "";
        problems.add("forbidden-element", `<${name}> is not allowed${hint}`, path.node.loc?.start);
      }
      if (name === "Figure") {
        const asset = path.node.attributes.find((a) => a.type === "JSXAttribute" && a.name.name === "asset");
        const value = asset?.value?.type === "StringLiteral" ? asset.value.value
          : asset?.value?.expression?.type === "StringLiteral" ? asset.value.expression.value : null;
        if (!asset) problems.add("figure-asset", "<Figure> needs an asset", path.node.loc?.start);
        else if (value === null) problems.add("figure-asset", "<Figure asset> must be a string literal asset id", path.node.loc?.start);
        else if (!assetIds.includes(value)) problems.add("figure-asset", `<Figure asset="${value}"> refers to an asset that does not exist`, path.node.loc?.start);
      }
    },
    JSXAttribute(path) {
      if (path.node.name.name === "dangerouslySetInnerHTML") {
        problems.add("forbidden-attribute", "dangerouslySetInnerHTML is not allowed", path.node.loc?.start);
      }
    },

    StringLiteral(path) {
      if (URL_PATTERN.test(path.node.value)) {
        problems.add("no-url", "URLs are not allowed in lesson code; media goes through <Figure asset>", path.node.loc?.start);
      }
    },
    TemplateElement(path) {
      if (URL_PATTERN.test(path.node.value.raw)) {
        problems.add("no-url", "URLs are not allowed in lesson code; media goes through <Figure asset>", path.node.loc?.start);
      }
    },
    JSXText(path) {
      if (/\bhttps?:\/\//i.test(path.node.value)) {
        problems.add("no-url", "URLs are not allowed in lesson code", path.node.loc?.start);
      }
    },
    CallExpression(path) {
      // new Function / Function() / eval are caught as references; also block `x.call` tricks on constructors via members.
      const callee = path.node.callee;
      if (callee.type === "Identifier" && callee.name === "setTimeout" && path.node.arguments[0]?.type === "StringLiteral") {
        problems.add("forbidden-global", "setTimeout with a string runs code and is not allowed", path.node.loc?.start);
      }
    },
  });

  if (usesSetInterval && !clearsInterval) {
    problems.add("interval-cleanup", "setInterval without clearInterval: clear it in the useEffect cleanup", null);
  }
  for (const name of required) {
    if (!declared.has(name)) problems.add("required", `Declare \`function ${name}() { … }\``, null);
  }
}

function checkCode(request) {
  const problems = new Problems();
  const code = String(request.code ?? "");
  if (!code.trim()) {
    problems.add("empty", "The code is empty", null);
    return problems.list;
  }
  if (!syntaxProblems(code, problems)) return problems.list;
  let ast;
  try {
    ast = parse(code, { sourceType: "module", plugins: ["jsx", "typescript"], errorRecovery: false, allowReturnOutsideFunction: true });
  } catch (error) {
    problems.add("syntax", error.message, error.loc && { line: error.loc.line, column: error.loc.column });
    return problems.list;
  }
  securityProblems(
    ast,
    { required: request.required ?? [], components: request.components ?? [], assetIds: request.assetIds ?? [] },
    problems,
  );
  return problems.list;
}

function checkLatex(request) {
  const errors = [];
  for (const item of request.items ?? []) {
    try {
      katex.renderToString(String(item), { throwOnError: true, strict: "ignore", trust: false });
    } catch (error) {
      errors.push({ item, message: String(error.message ?? error).replace(/^KaTeX parse error: /, "") });
    }
  }
  return errors;
}

const request = JSON.parse(readFileSync(0, "utf8"));
const errors = request.mode === "latex" ? checkLatex(request) : checkCode(request);
process.stdout.write(JSON.stringify({ ok: errors.length === 0, errors }));
process.exit(errors.length === 0 ? 0 : 1);
