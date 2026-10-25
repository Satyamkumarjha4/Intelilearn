import React, { Component, useEffect, useState } from "react";

import { describeError, post } from "./host";

type PageEntry = { key: string; title: string; render: () => React.ReactElement };

/** Lets the host (or the render check) open a page by key: `{type: "goto", page}`. */
function useGoto(setIndex: (i: number) => void, pages: PageEntry[]) {
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.data?.type !== "goto") return;
      const found = pages.findIndex((p) => p.key === event.data.page);
      if (found >= 0) setIndex(found);
    };
    const w = window as unknown as { __goto?: (key: string) => void };
    w.__goto = (key: string) => setIndex(Math.max(0, pages.findIndex((p) => p.key === key)));
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [pages, setIndex]);
}

/** The document's frame: page navigation (Introduction · Core · Advanced · Test) and a progress bar. */
export function LessonShell({ pages }: { pages: PageEntry[] }) {
  const [index, setIndex] = useState(0);
  useGoto(setIndex, pages);
  const page = pages[index];
  const Page = page.render;
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-4">
      <nav aria-label="Lesson pages" className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-1" role="tablist">
          {pages.map((p, i) => (
            <button
              key={p.key}
              type="button"
              role="tab"
              data-lesson-nav
              aria-selected={i === index}
              onClick={() => setIndex(i)}
              className={"rounded-lg px-3 py-1.5 text-sm font-medium " + (i === index ? "bg-primary text-primary-foreground" : "hover:bg-muted")}
            >
              {p.key === "test" ? "Test" : p.key[0].toUpperCase() + p.key.slice(1)}
            </button>
          ))}
        </div>
        <div className="h-1 w-full overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={index + 1} aria-valuemin={1} aria-valuemax={pages.length}>
          <div className="h-full bg-primary transition-all" style={{ width: `${((index + 1) / pages.length) * 100}%` }} />
        </div>
      </nav>
      <main data-page={page.key}>
        <Page />
      </main>
      <footer className="flex justify-between">
        <button type="button" data-lesson-nav disabled={index === 0} className="rounded-lg border px-3 py-1.5 text-sm disabled:opacity-40" onClick={() => setIndex(index - 1)}>
          Previous
        </button>
        <button type="button" data-lesson-nav disabled={index === pages.length - 1} className="rounded-lg border px-3 py-1.5 text-sm disabled:opacity-40" onClick={() => setIndex(index + 1)}>
          Next
        </button>
      </footer>
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
