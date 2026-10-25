"use client";

import { useEffect, useState } from "react";

import { lessonsApi } from "@/lib/lessons-api";
import type { QuizReview } from "@/lib/types";

/**
 * The answered quick check with each question's band and the learner's own answer, which is what tells "I don't know"
 * from a wrong answer. Only asked for once there is something to show, and a failure just means a plainer card.
 */
export function useDiagnosticReview(lessonId: string, enabled: boolean): QuizReview | null {
  const [review, setReview] = useState<QuizReview | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    lessonsApi
      .review(lessonId, "diagnostic")
      .then((data) => active && setReview(data))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [lessonId, enabled]);
  return review;
}
