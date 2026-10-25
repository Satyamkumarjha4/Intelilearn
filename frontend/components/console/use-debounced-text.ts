"use client";

import { useEffect, useRef, useState } from "react";

/**
 * A text box whose value is written to the address a moment after typing stops. `committed` is what the address says
 * now; when it changes by itself (back, a link) the box follows it. Returns the text and its setter.
 */
export function useDebouncedText(committed: string, commit: (text: string) => void, delayMs = 300) {
  const [text, setText] = useState(committed);
  const [seen, setSeen] = useState(committed);
  if (seen !== committed) {
    setSeen(committed);
    // Not when it is only our own (trimmed) write coming back: that would eat a space typed after the pause.
    if (committed !== text.trim()) setText(committed);
  }

  // The latest `commit` is read when the timer fires, so a new function each render does not restart the pause.
  const latest = useRef(commit);
  useEffect(() => {
    latest.current = commit;
  });
  useEffect(() => {
    if (text.trim() === committed.trim()) return;
    const timer = setTimeout(() => latest.current(text.trim()), delayMs);
    return () => clearTimeout(timer);
  }, [text, committed, delayMs]);

  return [text, setText] as const;
}
