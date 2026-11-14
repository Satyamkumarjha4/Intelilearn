/** What `GET /auth/captcha` says: whether the sign-up check is on, and the public key its widget needs (empty when off). */
export type CaptchaConfig = { enabled: boolean; site_key: string };

/** The one thing the widget script gives us. Only the calls we make are typed. */
export type TurnstileApi = {
  render: (
    container: HTMLElement,
    options: {
      sitekey: string;
      theme?: "auto" | "light" | "dark";
      callback: (token: string) => void;
      "expired-callback": () => void;
      "error-callback": () => void;
    },
  ) => string;
  remove: (widgetId: string) => void;
};

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

/** The rules of the check, apart from the screens that show it. */
export class CaptchaRules {
  static readonly OFF: CaptchaConfig = { enabled: false, site_key: "" };

  /** The answer of the server as a config, tolerating anything else: a check that cannot be read is treated as off
   *  (the server still refuses, with a sentence, if it was on). */
  static parse(value: unknown): CaptchaConfig {
    if (typeof value !== "object" || value === null) return CaptchaRules.OFF;
    const { enabled, site_key: siteKey } = value as Record<string, unknown>;
    return enabled === true && typeof siteKey === "string" && siteKey !== "" ? { enabled: true, site_key: siteKey } : CaptchaRules.OFF;
  }

  /** Whether the form may be sent: always when the check is off, otherwise only with a token. */
  static canSend(config: CaptchaConfig, token: string | null): boolean {
    return !config.enabled || Boolean(token);
  }

  /** `captcha_token` is added to a request only when there is one (the server ignores it while the check is off). */
  static withToken<T extends object>(body: T, token: string | null): T | (T & { captcha_token: string }) {
    return token ? { ...body, captcha_token: token } : body;
  }
}

/** Loads Cloudflare's widget script once. */
export class TurnstileScript {
  static readonly URL = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
  private static pending: Promise<TurnstileApi> | null = null;

  static load(doc: Document = document): Promise<TurnstileApi> {
    if (window.turnstile) return Promise.resolve(window.turnstile);
    TurnstileScript.pending ??= new Promise<TurnstileApi>((resolve, reject) => {
      const script = doc.createElement("script");
      script.src = TurnstileScript.URL;
      script.async = true;
      script.onload = () => (window.turnstile ? resolve(window.turnstile) : reject(new Error("Turnstile did not start")));
      script.onerror = () => {
        TurnstileScript.pending = null; // a later try may work
        reject(new Error("Turnstile could not be loaded"));
      };
      doc.head.appendChild(script);
    });
    return TurnstileScript.pending;
  }
}
