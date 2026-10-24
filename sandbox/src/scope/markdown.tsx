import "katex/dist/katex.min.css";
import katex from "katex";
import React from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkMath from "remark-math";

import { CodeBlock } from "./code";

function MarkdownCode({ className, children }: { className?: string; children?: React.ReactNode }) {
  const language = /language-(\w+)/.exec(className ?? "")?.[1];
  const text = String(children ?? "");
  if (!language && !text.includes("\n")) return <code className="rounded bg-muted px-1 font-mono text-[0.9em]">{text}</code>;
  return <CodeBlock code={text.replace(/\n$/, "")} language={language ?? "text"} />;
}

/** Markdown with LaTeX between $…$ or $$…$$ (KaTeX). Raw HTML in the text is not rendered. */
export function Markdown({ children }: { children?: string }) {
  return (
    <div className="flex flex-col gap-3 leading-relaxed [&_ol]:list-decimal [&_ol]:pl-6 [&_ul]:list-disc [&_ul]:pl-6">
      <ReactMarkdown
        remarkPlugins={[remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{ code: MarkdownCode as never, pre: ({ children: c }) => <>{c}</> }}
      >
        {String(children ?? "")}
      </ReactMarkdown>
    </div>
  );
}

function math(source: string, displayMode: boolean) {
  try {
    return katex.renderToString(source, { displayMode, throwOnError: false, strict: "ignore", trust: false });
  } catch {
    return source;
  }
}

export function InlineMath({ children }: { children?: React.ReactNode }) {
  return <span dangerouslySetInnerHTML={{ __html: math(String(children ?? ""), false) }} />;
}

export function BlockMath({ children }: { children?: React.ReactNode }) {
  return <div className="overflow-x-auto" dangerouslySetInnerHTML={{ __html: math(String(children ?? ""), true) }} />;
}
