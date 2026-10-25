import type { LessonDocument, RepairError } from "@/lib/types";

/** A crash reported by the lesson runtime inside the iframe. */
export type SandboxError = {
  phase: "transform" | "runtime";
  message: string;
  stack: string;
  codeVersion: number;
  /** Set when an interactive's own error boundary caught it. */
  component?: string;
  page?: string;
};

/** What the runtime posts to the page that embeds it (sandbox/src/runtime.tsx). */
export type SandboxMessage =
  | { type: "ready" }
  | { type: "rendered"; codeVersion: number; height: number }
  | { type: "height"; height: number }
  | { type: "error"; error: SandboxError }
  | { type: "test_submit"; answers: Record<string, unknown> };

const text = (value: unknown): string => (typeof value === "string" ? value : "");
const count = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) ? value : 0);

/** Reads what came out of `postMessage`. The iframe runs generated code, so nothing in it is trusted to have a shape. */
export class SandboxMessages {
  static parse(data: unknown): SandboxMessage | null {
    if (!data || typeof data !== "object") return null;
    const message = data as Record<string, unknown>;
    switch (message.type) {
      case "ready":
        return { type: "ready" };
      case "rendered":
        return { type: "rendered", codeVersion: count(message.codeVersion), height: count(message.height) };
      case "height":
        return { type: "height", height: count(message.height) };
      case "error":
        return {
          type: "error",
          error: {
            phase: message.phase === "transform" ? "transform" : "runtime",
            message: text(message.message) || "Unknown error",
            stack: text(message.stack),
            codeVersion: count(message.codeVersion),
            ...(typeof message.component === "string" ? { component: message.component } : {}),
            ...(typeof message.page === "string" ? { page: message.page } : {}),
          },
        };
      case "test_submit": {
        const answers = message.answers;
        if (!answers || typeof answers !== "object" || Array.isArray(answers)) return null;
        return { type: "test_submit", answers: answers as Record<string, unknown> };
      }
      default:
        return null;
    }
  }

  /** Only the iframe we embedded may talk to us: any other window's message is dropped. */
  static from(event: { source: unknown; data: unknown }, frame: unknown): SandboxMessage | null {
    return frame && event.source === frame ? SandboxMessages.parse(event.data) : null;
  }
}

/** The harness page (served at /sandbox/harness.html) with the addresses of the runtime filled in. */
export class HarnessBuilder {
  constructor(private readonly origin: string) {}

  /** The iframe has an opaque origin, so every address in it is absolute; the CSP allows scripts and images from
   *  this origin only and nothing else (no network access for generated code). */
  html(template: string): string {
    return template
      .replaceAll("__ASSETS__", this.origin)
      .replaceAll("__MEDIA__", this.origin)
      .replace("__RUNTIME_CSS__", `${this.origin}/sandbox/runtime.css`)
      .replace("__TAILWIND__", `${this.origin}/sandbox/tailwind.js`)
      .replace("__RUNTIME__", `${this.origin}/sandbox/runtime.js`);
  }

  /** The lesson data with each media URL made absolute (relative ones would resolve against the opaque origin). */
  absolute(document: LessonDocument): LessonDocument {
    const media = Object.fromEntries(
      Object.entries(document.data.media ?? {}).map(([id, entry]) => [id, { ...entry, url: new URL(entry.url, this.origin).href }]),
    );
    return { ...document, data: { ...document.data, media } };
  }
}

/** Fetches the harness page once and reuses it (a failed fetch is not remembered, so the next try can succeed). */
export class HarnessSource {
  private cached: Promise<string> | null = null;

  constructor(
    private readonly fetcher: (url: string) => Promise<{ ok: boolean; text(): Promise<string> }> = (url) => fetch(url),
    private readonly path = "/sandbox/harness.html",
  ) {}

  load(): Promise<string> {
    this.cached ??= this.fetcher(this.path)
      .then((response) => {
        if (!response.ok) throw new Error("The lesson viewer could not be loaded.");
        return response.text();
      })
      .catch((error: unknown) => {
        this.cached = null;
        throw error;
      });
    return this.cached;
  }
}

export const harnessSource = new HarnessSource();

/** The message that starts (or restarts) the runtime on a document. */
export class RenderMessage {
  static of(document: LessonDocument, theme: "light" | "dark") {
    return { type: "render", code: document.code, data: document.data, codeVersion: document.code_version, theme };
  }
}

/** What the API is told when the browser reports a crash (the server finds the broken part from it). */
export class RepairReport {
  static of(error: SandboxError): RepairError {
    const named = error.component ? `${error.component} crashed: ${error.message}` : error.message;
    return {
      message: named.slice(0, 2000),
      ...(error.stack ? { stack: error.stack.slice(0, 8000) } : {}),
      ...(error.page ? { page: error.page.slice(0, 20) } : {}),
    };
  }
}

/**
 * Decides whether a crash is reported for an automatic repair: once per version of the code (one crash usually
 * raises several errors, and one repair covers them), never for an error from a version the page has moved past,
 * and never again once the server has said the repair limit is reached.
 */
export class RepairGate {
  private tried = new Set<number>();
  private stopped = false;

  shouldRepair(error: SandboxError, currentVersion: number): boolean {
    if (this.stopped || error.codeVersion !== currentVersion || this.tried.has(currentVersion)) return false;
    this.tried.add(currentVersion);
    return true;
  }

  /** The server refused: the limit is reached, so nothing is requested automatically any more. */
  stop(): void {
    this.stopped = true;
  }

  get isStopped(): boolean {
    return this.stopped;
  }
}
