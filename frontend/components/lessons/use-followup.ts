"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { FollowupMaker } from "@/lib/followup-maker";
import type { OfferStep } from "@/lib/followup-offer";
import { lessonsApi } from "@/lib/lessons-api";

/** Presses an offer's button: makes the lesson (or opens the one that exists) and goes there. */
export function useFollowup(lessonId: string) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  const take = async (step: OfferStep): Promise<boolean> => {
    if (step.intent === "open") {
      router.push(`/lessons/${step.lessonId}`);
      return true;
    }
    setBusy(true);
    const result = await new FollowupMaker(lessonsApi).make(lessonId, step.level);
    if (result.kind === "open") {
      router.push(`/lessons/${result.lessonId}`);
      return true; // stay busy while the page changes, so a second press cannot start another
    }
    toast.error(result.message);
    setBusy(false);
    return false;
  };

  return { busy, take };
}
