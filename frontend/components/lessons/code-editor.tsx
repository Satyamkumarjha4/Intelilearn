"use client";

import { defaultKeymap, history, historyKeymap, indentWithTab, temporarilySetTabFocusMode } from "@codemirror/commands";
import { bracketMatching, indentOnInput, indentUnit, type LanguageSupport } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import { EditorView, keymap, lineNumbers, placeholder } from "@codemirror/view";
import { useEffect, useRef } from "react";

import { type CodeLanguage, CodeLanguages } from "@/lib/code-languages";

/** One language pack, loaded the first time a question asks for it. `plain` has none. */
const PACKS: Record<CodeLanguage, (() => Promise<LanguageSupport>) | null> = {
  python: () => import("@codemirror/lang-python").then((m) => m.python()),
  javascript: () => import("@codemirror/lang-javascript").then((m) => m.javascript()),
  typescript: () => import("@codemirror/lang-javascript").then((m) => m.javascript({ typescript: true })),
  java: () => import("@codemirror/lang-java").then((m) => m.java()),
  cpp: () => import("@codemirror/lang-cpp").then((m) => m.cpp()),
  plain: null,
};

type Props = {
  value: string;
  onChange: (value: string) => void;
  /** The language as the question names it ("Python 3", "js"); the pack is chosen from it. */
  language?: string;
  label: string;
  disabled?: boolean;
  /** Greyed text while the box is empty. */
  hint?: string;
};

/**
 * A code editor (CodeMirror 6) for a written answer about code. It is loaded only on pages that have a code question
 * (`code-editor-loader.tsx`), and its language pack only when the question asks for it. Tab indents, which is what code
 * needs; so that a keyboard user is never trapped, Esc turns that off for the next key (Esc, then Tab, leaves), and the
 * editor says so under itself.
 */
export function CodeEditor({ value, onChange, language, label, disabled = false, hint }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const change = useRef(onChange);
  useEffect(() => {
    change.current = onChange; // the editor is made once; it calls whatever handler the page has now
  });

  useEffect(() => {
    let alive = true;
    const element = host.current;
    if (!element) return;
    const pack = PACKS[CodeLanguages.of(language)];
    void (pack ? pack() : Promise.resolve(null)).then((support) => {
      if (!alive) return;
      view.current = new EditorView({
        parent: element,
        state: EditorState.create({
          doc: value,
          extensions: [
            lineNumbers(),
            history(),
            bracketMatching(),
            indentOnInput(),
            indentUnit.of("    "),
            EditorView.lineWrapping,
            EditorView.contentAttributes.of({ "aria-label": label, "aria-multiline": "true" }),
            EditorView.editable.of(!disabled),
            EditorState.readOnly.of(disabled),
            keymap.of([{ key: "Escape", run: temporarilySetTabFocusMode }, indentWithTab, ...defaultKeymap, ...historyKeymap]),
            ...(hint ? [placeholder(hint)] : []),
            ...(support ? [support] : []),
            EditorView.updateListener.of((update) => {
              if (update.docChanged) change.current(update.state.doc.toString());
            }),
          ],
        }),
      });
    });
    return () => {
      alive = false;
      view.current?.destroy();
      view.current = null;
    };
    // The editor is made once for a question; its text then lives in the editor, and `value` only seeds it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language, disabled, label]);

  return (
    <div className="flex flex-col gap-1.5">
      <div
        ref={host}
        className="min-h-48 overflow-hidden rounded-xl border-2 border-border bg-card font-mono text-sm focus-within:ring-3 focus-within:ring-ring/50 [&_.cm-editor]:min-h-48 [&_.cm-editor]:outline-none [&_.cm-gutters]:border-0 [&_.cm-gutters]:bg-muted [&_.cm-scroller]:font-mono"
      />
      {!disabled && <p className="text-xs text-muted-foreground">{CodeLanguages.LEAVE_HINT}</p>}
    </div>
  );
}
