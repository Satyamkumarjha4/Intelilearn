import type { ProbeResult } from "@/lib/types";

export type ProbeHooks = {
  onStart?: (id: number) => void;
  onResult?: (id: number, result: ProbeResult) => void;
};

const UNSENT: ProbeResult = {
  ok: false,
  latency_s: null,
  error: "The test could not be sent. Check the connection and try again.",
  checks: [],
};

/**
 * Runs model tests a few at a time. A test makes real provider calls and may take twenty seconds, so all at once would
 * trip the providers' rate limits; one at a time would make the staff wait for the slowest. Each result is reported as
 * it arrives, and a test that cannot be sent counts as a failed result instead of ending the queue.
 */
export class ProbeQueue {
  static readonly CONCURRENCY = 2;

  constructor(
    private readonly probe: (id: number) => Promise<ProbeResult>,
    private readonly concurrency: number = ProbeQueue.CONCURRENCY,
  ) {}

  /** Resolves when every test has finished. Set `signal.stopped` to start no more (the running ones finish). */
  async run(ids: readonly number[], hooks: ProbeHooks, signal: { stopped: boolean } = { stopped: false }): Promise<void> {
    const waiting = [...new Set(ids)];
    const worker = async () => {
      for (let id = waiting.shift(); id !== undefined && !signal.stopped; id = waiting.shift()) {
        hooks.onStart?.(id);
        // awaited first: `hooks.onResult?.(id, await …)` would skip the test itself when there is no hook
        const result = await this.attempt(id);
        hooks.onResult?.(id, result);
      }
    };
    await Promise.all(Array.from({ length: Math.min(this.concurrency, waiting.length) }, worker));
  }

  private async attempt(id: number): Promise<ProbeResult> {
    try {
      return await this.probe(id);
    } catch {
      return UNSENT;
    }
  }
}
