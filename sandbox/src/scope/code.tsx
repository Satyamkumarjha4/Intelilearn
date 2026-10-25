import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import cpp from "highlight.js/lib/languages/cpp";
import java from "highlight.js/lib/languages/java";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import python from "highlight.js/lib/languages/python";
import typescript from "highlight.js/lib/languages/typescript";
import React from "react";

hljs.registerLanguage("bash", bash);
hljs.registerLanguage("cpp", cpp);
hljs.registerLanguage("java", java);
hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("json", json);
hljs.registerLanguage("python", python);
hljs.registerLanguage("typescript", typescript);
const ALIASES: Record<string, string> = { py: "python", js: "javascript", ts: "typescript", "c++": "cpp", sh: "bash" };

function highlight(code: string, language: string): string {
  const name = ALIASES[language] ?? language;
  if (hljs.getLanguage(name)) return hljs.highlight(code, { language: name, ignoreIllegals: true }).value;
  return code.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]!);
}

export function CodeBlock({ code, language = "text" }: { code: string; language?: string }) {
  return (
    <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-sm">
      <code className="font-mono" data-language={language} dangerouslySetInnerHTML={{ __html: highlight(code, language) }} />
    </pre>
  );
}
