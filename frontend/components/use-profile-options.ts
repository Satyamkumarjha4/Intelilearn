"use client";

import { useEffect, useState } from "react";

import { apiClient } from "@/lib/api";
import { OnboardingChoices, ONBOARDING_COPY, type ApiChoice, type Choice } from "@/lib/onboarding-flow";

type Options = Record<string, ApiChoice[]>;
type Field = keyof typeof ONBOARDING_COPY;

/** What the API accepts for each profile question (`GET /profile/options`). Until it answers, or if it can't, the
 *  usual tiles are shown. */
export function useProfileOptions() {
  const [options, setOptions] = useState<Options | null>(null);
  useEffect(() => {
    let active = true;
    apiClient
      .request<Options>("/profile/options")
      .then((data) => active && setOptions(data))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);
  return (field: Field): Choice[] => OnboardingChoices.merge(ONBOARDING_COPY[field], options?.[field]);
}
