import type { APIRequestContext } from "@playwright/test";

import { Api } from "./api";

/**
 * The mail the throwaway stack "sent": its `outbox` backend keeps the text on the mail log row and `GET /api/dev/outbox`
 * (a 404 anywhere else) lists it, so a browser test can read the code a learner would find in their inbox.
 */
export class Outbox {
  /** The six digits in the newest message of `kind` to `email`, waiting for the worker to deliver it. */
  static async code(request: APIRequestContext, email: string, kind: "signup_code" | "login_code" = "signup_code", after = 0): Promise<string> {
    const read = async () => {
      const response = await request.get(`/api/dev/outbox?email=${encodeURIComponent(email)}`);
      const messages: { kind: string; text: string }[] = (await response.json().catch(() => ({ messages: [] }))).messages ?? [];
      return messages.filter((message) => message.kind === kind && message.text);
    };
    const found = await Api.poll(read, (messages) => messages.length > after, 30_000, `the ${kind} email to ${email}`);
    return Outbox.digits(found[0].text);
  }

  /** On the "Check your email" screen after creating an account: types the code the outbox holds and waits for onboarding. */
  static async enterCode(page: import("@playwright/test").Page, email: string): Promise<void> {
    await page.waitForURL(/\/auth\/verify/);
    await page.getByLabel("6-digit code").fill(await Outbox.code(page.request, email));
    await page.waitForURL(/\/onboarding/);
  }

  /** The code in a message's text. */
  static digits(text: string): string {
    const match = text.match(/\b(\d{6})\b/);
    if (!match) throw new Error("no six-digit code in the message");
    return match[1];
  }

  /** How many messages of `kind` are there already (so a resend can wait for the next one). */
  static async count(request: APIRequestContext, email: string, kind: string): Promise<number> {
    const response = await request.get(`/api/dev/outbox?email=${encodeURIComponent(email)}`);
    const messages: { kind: string; text: string }[] = (await response.json()).messages ?? [];
    return messages.filter((message) => message.kind === kind && message.text).length;
  }
}
