import { expect, type BrowserContext, type Page } from "@playwright/test";

import { Outbox } from "./outbox";

type Reply<T = any> = { status: number; body: T };

/** The app's own API through the page's session, with the CSRF header the browser would send. */
export class Api {
  constructor(private readonly page: Page) {}

  private get context(): BrowserContext {
    return this.page.context();
  }

  private async csrf(): Promise<string> {
    const read = async () => (await this.context.cookies()).find((cookie) => cookie.name === "csrftoken")?.value ?? "";
    return (await read()) || (await this.page.request.get("/api/auth/csrf").then(read));
  }

  async call<T = any>(method: string, path: string, data?: unknown): Promise<Reply<T>> {
    const response = await this.page.request.fetch(`/api${path}`, {
      method,
      data,
      headers: { "X-CSRFToken": await this.csrf(), "Content-Type": "application/json" },
    });
    return { status: response.status(), body: (await response.json().catch(() => null)) as T };
  }

  /** A learner with a finished profile, signed in on this page's browser context: the way a person gets there, a code from
   *  their inbox (the throwaway stack's outbox) entered by the browser that registered. */
  async signUp(email: string, password: string, name = "E2E Learner"): Promise<void> {
    const registered = await this.call("POST", "/auth/register", { name, email, password, accept_terms: true });
    expect(registered.status, "register should accept the sign-up").toBe(202);
    const code = await Outbox.code(this.page.request, email);
    const verified = await this.call("POST", "/auth/verify", { email, code, purpose: "signup" });
    expect(verified.status, "the emailed code should create the account").toBe(200);
    await this.call("PUT", "/profile", {
      education_level: "school",
      grade_or_year: "9",
      field_of_study: "",
      learning_preference: "mixed",
      goal: "exam_prep",
      preferred_language: "en",
      notes: "",
    });
  }

  stage(lessonId: string) {
    return this.call<{ stage: string; active_run_id: string | null }>("GET", `/lessons/${lessonId}`).then((reply) => reply.body.stage);
  }

  /** Polls until `done` is true for the lesson (or the time is up, which fails the test with what it last saw). */
  async until(lessonId: string, done: (lesson: any) => boolean, ms = 120_000): Promise<any> {
    return Api.poll(() => this.call("GET", `/lessons/${lessonId}`).then((reply) => reply.body), done, ms, "the lesson");
  }

  /** Reads until `done` is true, quickly at first (a state change is usually a second or two away) and then every second. The
   *  failure says what was last seen. Used by every wait for a build, so none of them sleeps for a fixed time. */
  static async poll<T>(read: () => Promise<T>, done: (seen: T) => boolean, ms: number, what: string): Promise<T> {
    let last: T | null = null;
    await expect
      .poll(async () => done((last = await read())), { timeout: ms, intervals: [250, 250, 500, 1000], message: `${what} did not get there in ${ms} ms` })
      .toBe(true);
    return last as T;
  }
}
