/**
 * Unit under test: `AuthApi`, the typed calls of the sign-in endpoints.
 *
 * Why: the sign-up flow is two requests with different answers (a status, then a user), and the screens depend on the exact
 * paths and bodies. A client that fakes the network checks them without a server.
 *
 * Use cases:
 * - `register` posts the body and returns nothing (no user exists yet)
 * - `verify` posts the email, code and purpose and returns the user
 * - `forgot` posts the email; `reset` posts the email, code and new password (as `new_password`) and returns the user, and
 *   a weak password reaches the caller as an error with its field messages
 * - `resend` posts the email and purpose
 * - `login` returns the user, and a `verification_required` answer reaches the caller as an error
 */
import { describe, expect, test } from "bun:test";

import { ApiClient, ApiError } from "./api";
import { AuthApi } from "./auth-api";

function setup(answer: (path: string, init: RequestInit) => Response) {
  const seen: { path: string; method?: string; body: unknown }[] = [];
  const client = new ApiClient(
    async (input, init = {}) => {
      seen.push({ path: input, method: init.method, body: init.body ? JSON.parse(String(init.body)) : undefined });
      return answer(input, init);
    },
    () => "csrf-token",
  );
  return { api: new AuthApi(client), seen };
}

const USER = { id: "1", email: "ada@example.com", name: "Ada", profile_complete: false, is_staff: false };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("AuthApi", () => {
  test("register posts the body and returns nothing", async () => {
    const { api, seen } = setup(() => json({ status: "verification_required" }, 202));

    expect(await api.register({ email: "ada@example.com", name: "Ada" })).toBeUndefined();
    expect(seen).toEqual([{ path: "/api/auth/register", method: "POST", body: { email: "ada@example.com", name: "Ada" } }]);
  });

  test("verify posts the email, code and purpose and returns the user", async () => {
    const { api, seen } = setup(() => json({ user: USER }));

    expect(await api.verify("ada@example.com", "123456", "signup")).toEqual(USER);
    expect(seen[0]).toEqual({ path: "/api/auth/verify", method: "POST", body: { email: "ada@example.com", code: "123456", purpose: "signup" } });
  });

  test("a wrong code reaches the caller as an error with the one code", async () => {
    const { api } = setup(() => json({ detail: "That code didn't work.", code: "invalid_code" }, 400));

    const failure = await api.verify("ada@example.com", "000000", "signup").catch((e) => e);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure.code).toBe("invalid_code");
  });

  test("forgot posts the email and returns nothing", async () => {
    const { api, seen } = setup(() => json({ status: "sent" }, 202));

    expect(await api.forgot("ada@example.com")).toBeUndefined();
    expect(seen).toEqual([{ path: "/api/auth/password/forgot", method: "POST", body: { email: "ada@example.com" } }]);
  });

  test("reset posts the email, code and new password and returns the user", async () => {
    const { api, seen } = setup(() => json({ user: USER }));

    expect(await api.reset("ada@example.com", "123456", "tulip-garden-7")).toEqual(USER);
    expect(seen[0]).toEqual({ path: "/api/auth/password/reset", method: "POST", body: { email: "ada@example.com", code: "123456", new_password: "tulip-garden-7" } });
  });

  test("a weak password reaches the caller with its field messages, and a wrong code with the one code", async () => {
    const weak = setup(() => json({ detail: "Please correct the highlighted fields.", code: "invalid", fields: { new_password: ["This password is too common."] } }, 400));
    const failure = await weak.api.reset("ada@example.com", "123456", "password").catch((e) => e);
    expect(failure.fields).toEqual({ new_password: ["This password is too common."] });

    const wrong = setup(() => json({ detail: "That code didn't work.", code: "invalid_code" }, 400));
    expect((await wrong.api.reset("ada@example.com", "000000", "tulip-garden-7").catch((e) => e)).code).toBe("invalid_code");
  });

  test("resend posts the email and purpose", async () => {
    const { api, seen } = setup(() => json({ status: "sent" }, 202));

    await api.resend("ada@example.com", "login");
    expect(seen[0]).toEqual({ path: "/api/auth/verify/resend", method: "POST", body: { email: "ada@example.com", purpose: "login" } });
  });

  test("login returns the user, and an unverified email is an error the screen can act on", async () => {
    const ok = setup(() => json({ user: USER }));
    expect(await ok.api.login("ada@example.com", "pw")).toEqual(USER);

    const unverified = setup(() => json({ detail: "Check your email", code: "verification_required" }, 403));
    const failure = await unverified.api.login("ada@example.com", "pw").catch((e) => e);
    expect(failure.code).toBe("verification_required");
    expect(failure.status).toBe(403);
  });
});
