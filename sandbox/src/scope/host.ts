// How the runtime talks to whoever embeds it: the parent page when it is framed, or the render check's host function
// when it is loaded top-level by Playwright (`window.__lessonHost`).
export type HostMessage = Record<string, unknown> & { type: string };

export function post(message: HostMessage): void {
  const w = window as unknown as { __lessonHost?: (m: HostMessage) => void };
  if (window.parent !== window) window.parent.postMessage(message, "*");
  else if (w.__lessonHost) w.__lessonHost(message);
}

export function describeError(error: unknown): { message: string; stack: string } {
  if (error instanceof Error) return { message: error.message, stack: (error.stack ?? "").slice(0, 2000) };
  return { message: String(error), stack: "" };
}
