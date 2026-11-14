"use client";

import { useEffect, useRef, useState } from "react";

import { type CaptchaConfig, TurnstileScript } from "@/lib/captcha";

type Props = {
  config: CaptchaConfig;
  /** The token once the visitor has passed, and null when it ran out or the check failed. */
  onToken: (token: string | null) => void;
  /** Change it to ask for a new check (a token works once, so a refused form needs a new one). */
  resetKey?: number;
};

/** Cloudflare Turnstile, drawn only when the check is on. It says what it is doing in words for people who cannot see it. */
export function CaptchaWidget({ config, onToken, resetKey = 0 }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const callback = useRef(onToken);
  const [failed, setFailed] = useState(false);

  // The widget calls whichever handler is newest, without being drawn again when the screen re-renders.
  useEffect(() => {
    callback.current = onToken;
  });

  useEffect(() => {
    if (!config.enabled || !box.current) return;
    let id: string | null = null;
    let gone = false;
    callback.current(null);
    setFailed(false);
    TurnstileScript.load()
      .then((turnstile) => {
        if (gone || !box.current) return;
        id = turnstile.render(box.current, {
          sitekey: config.site_key,
          theme: "auto",
          callback: (token) => callback.current(token),
          "expired-callback": () => callback.current(null),
          "error-callback": () => callback.current(null),
        });
      })
      .catch(() => setFailed(true));
    return () => {
      gone = true;
      if (id !== null) window.turnstile?.remove(id);
    };
  }, [config.enabled, config.site_key, resetKey]);

  if (!config.enabled) return null;
  return (
    <div className="grid gap-1">
      <div ref={box} aria-label="Security check" />
      {failed ? (
        <p role="alert" className="text-sm font-semibold text-destructive-text">
          The security check could not load. Check your connection and reload the page.
        </p>
      ) : null}
    </div>
  );
}
