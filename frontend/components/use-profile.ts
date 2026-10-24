"use client";

import { useEffect, useState } from "react";

import { apiClient, ApiError } from "@/lib/api";
import type { Profile } from "@/lib/types";

/** Loads the signed-in user's profile once. */
export function useProfile() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    apiClient.request<Profile>("/profile")
      .then((data) => active && setProfile(data))
      .catch((err) => active && setError(err instanceof ApiError ? err.message : "Could not load your profile."));
    return () => {
      active = false;
    };
  }, []);

  return { profile, error };
}
