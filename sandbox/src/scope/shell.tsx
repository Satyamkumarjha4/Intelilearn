import React, { Component, useEffect, useMemo, useState } from "react";

import { describeError, isHiddenPage, post } from "./host";

type PageEntry = { key: string; title: string; render: () => React.ReactElement };

/**
 * Opens pages on request, from outside the document:
 * - `{type: "set_page", index}` from the app, which has its own book chrome (flaps, previous and next)
 * - `{type: "goto", page}` and `window.__goto(key)` from the render check, which visits pages by key
 */
function usePageControl(visible: PageEntry[], setIndex: (i: number) => void) {
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const message = event.data;
      if (message?.type === "set_page" && Number.isInteger(message.index)) {
        setIndex(Math.min(Math.max(message.index, 0), visible.length - 1));
      } else if (message?.type === "goto") {
        const found = visible.findIndex((p) => p.key === message.page);
        if (found >= 0) setIndex(found);
      }
    };
    const w = window as unknown as { __goto?: (key: string) => void };
    w.__goto = (key: string) => setIndex(Math.max(0, visible.findIndex((p) => p.key === key)));
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [visible, setIndex]);
}

/**
 * The document's frame. It shows one page at a time and has no navigation of its own: the app draws the book around it
 * (index flaps, previous and next) and drives it with `set_page`. It tells the app which pages there are (`pages`) and
 * which one is open (`page_changed`). Pages the app hides (`isHiddenPage`) are left out, so an older lesson that still
 * declares a test page does not show it.
 */
export function LessonShell({ pages }: { pages: PageEntry[] }) {
  const visible = useMemo(() => pages.filter((p) => !isHiddenPage(p.key)), [pages]);
  const [index, setIndex] = useState(0);
  usePageControl(visible, setIndex);
  const current = Math.min(index, visible.length - 1);

  useEffect(() => {
    post({ type: "pages", count: visible.length, titles: visible.map((p) => p.title) });
  }, [visible]);
  useEffect(() => {
    post({ type: "page_changed", index: current });
  }, [current]);

  const page = visible[current];
  const Page = page.render;
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-4">
      <main data-page={page.key}>
        <Page />
      </main>
    </div>
  );
}

type BoundaryProps = { name: string; children: React.ReactNode };

class Boundary extends Component<BoundaryProps, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    post({ type: "error", phase: "runtime", component: this.props.name, ...describeError(error) });
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return <p className="rounded-lg border border-destructive/40 p-3 text-sm text-destructive">This part of the lesson could not be shown.</p>;
  }
}

/** Wraps an interactive so one that crashes shows a message in its own place and is reported by name. */
export function withBoundary<P extends object>(name: string, Wrapped: React.ComponentType<P>) {
  const Guarded = (props: P) => (
    <Boundary name={name}>
      <Wrapped {...props} />
    </Boundary>
  );
  Guarded.displayName = name;
  return Guarded;
}

export { Boundary };
