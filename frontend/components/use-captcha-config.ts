"use client";

import { useEffect, useState } from "react";

import { AuthApi } from "@/lib/auth-api";
import { type CaptchaConfig, CaptchaRules } from "@/lib/captcha";

/** Whether the sign-up check is on. Off until the answer arrives (and if it never does), so a slow or failed look
 *  never keeps a form from being sent: the server is what insists on the check. */
export function useCaptchaConfig(): CaptchaConfig {
  const [config, setConfig] = useState<CaptchaConfig>(CaptchaRules.OFF);
  useEffect(() => {
    let alive = true;
    new AuthApi().captcha().then((found) => {
      if (alive) setConfig(found);
    });
    return () => {
      alive = false;
    };
  }, []);
  return config;
}
