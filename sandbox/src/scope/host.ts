// How the runtime talks to whoever embeds it: the parent page when it is framed, or the render check's host function
// when it is loaded top-level by Playwright (`window.__lessonHost`).
export type HostMessage = Record<string, unknown> & { type: string };

let currentCodeVersion = 0;

/** The version of the code being shown. The page that embeds the runtime ignores an error from a version it has moved
 *  past, so every error carries the version it belongs to, including those posted by an error boundary. */
export function setCodeVersion(version: number): void {
  currentCodeVersion = version;
}

export function post(message: HostMessage): void {
  const full = message.type === "error" && message.codeVersion === undefined ? { ...message, codeVersion: currentCodeVersion } : message;
  const w = window as unknown as { __lessonHost?: (m: HostMessage) => void };
  if (window.parent !== window) window.parent.postMessage(full, "*");
  else if (w.__lessonHost) w.__lessonHost(full);
}

export function describeError(error: unknown): { message: string; stack: string } {
  if (error instanceof Error) return { message: error.message, stack: (error.stack ?? "").slice(0, 2000) };
  return { message: String(error), stack: "" };
}
