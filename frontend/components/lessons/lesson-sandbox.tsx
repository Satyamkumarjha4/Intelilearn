"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { HarnessBuilder, harnessSource, RenderMessage, SandboxMessages, type SandboxMessage } from "@/lib/sandbox-bridge";
import type { LessonDocument } from "@/lib/types";

type Props = {
  document: LessonDocument;
  theme: "light" | "dark";
  onMessage: (message: SandboxMessage) => void;
};

/**
 * The lesson, running in a sandboxed iframe (docs/frontend.md): `allow-scripts` without `allow-same-origin` gives it an
 * opaque origin, and the harness's CSP lets it load only the runtime and our media, so generated code can neither reach
 * the app's cookies nor the network. It speaks only through `postMessage`, and only messages from this iframe are heard.
 */
export function LessonSandbox({ document: lesson, theme, onMessage }: Props) {
  const frame = useRef<HTMLIFrameElement>(null);
  const ready = useRef(false);
  const latest = useRef({ lesson, theme, onMessage });
  const [srcDoc, setSrcDoc] = useState<string | null>(null);
  const [height, setHeight] = useState(720);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    latest.current = { lesson, theme, onMessage };
  });

  useEffect(() => {
    let active = true;
    const builder = new HarnessBuilder(window.location.origin);
    harnessSource
      .load()
      .then((template) => active && setSrcDoc(builder.html(template)))
      .catch(() => active && setFailed(true));
    return () => {
      active = false;
    };
  }, []);

  const render = useCallback(() => {
    const builder = new HarnessBuilder(window.location.origin);
    const { lesson: current, theme: currentTheme } = latest.current;
    frame.current?.contentWindow?.postMessage(RenderMessage.of(builder.absolute(current), currentTheme), "*");
  }, []);

  useEffect(() => {
    const listen = (event: MessageEvent) => {
      const message = SandboxMessages.from(event, frame.current?.contentWindow);
      if (!message) return;
      if (message.type === "ready") {
        ready.current = true;
        render();
      } else if (message.type === "rendered" || message.type === "height") {
        setHeight(Math.max(message.height, 240));
      }
      latest.current.onMessage(message);
    };
    window.addEventListener("message", listen);
    return () => window.removeEventListener("message", listen);
  }, [render]);

  // A new version of the code (after a repair or a restore) is rendered in the same frame, once the runtime is up.
  useEffect(() => {
    if (ready.current) render();
  }, [lesson.code_version, lesson.code, render]);

  useEffect(() => {
    if (ready.current) frame.current?.contentWindow?.postMessage({ type: "theme", theme }, "*");
  }, [theme]);

  if (failed) {
    return (
      <Alert variant="destructive">
        <AlertDescription>The lesson viewer could not be loaded. Reload the page to try again.</AlertDescription>
      </Alert>
    );
  }
  if (!srcDoc) return <div className="h-96 rounded-lg border bg-muted/30" aria-busy="true" />;
  return (
    <iframe
      ref={frame}
      title="Lesson"
      sandbox="allow-scripts"
      srcDoc={srcDoc}
      className="w-full rounded-lg border bg-background"
      style={{ height }}
    />
  );
}
