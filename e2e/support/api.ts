import type { BrowserContext, Page } from "@playwright/test";

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

  /** A learner with a finished profile, signed in on this page's browser context. */
  async signUp(email: string, password: string, name = "E2E Learner"): Promise<void> {
    await this.call("POST", "/auth/register", { name, email, password, accept_terms: true });
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
    const deadline = Date.now() + ms;
    let last: any = null;
    while (Date.now() < deadline) {
      last = (await this.call("GET", `/lessons/${lessonId}`)).body;
      if (done(last)) return last;
      await this.page.waitForTimeout(1000);
    }
    throw new Error(`the lesson did not get there in ${ms} ms; last seen: ${last?.stage}`);
  }
}
