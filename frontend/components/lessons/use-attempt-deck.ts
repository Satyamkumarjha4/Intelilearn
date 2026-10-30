"use client";

import { useReducer, useState } from "react";

import { DeckSession, type DeckAnswer } from "@/lib/deck-session";

/**
 * The cards of an attempt. The server is where answers live (each is locked there when the learner moves on), so the
 * deck starts from what the server has: the questions already answered are behind the learner, and a refresh resumes on
 * the first card without an answer. Nothing is kept in `sessionStorage`.
 */
export function useAttemptDeck(ids: string[], saved: Record<string, unknown>) {
  const [deck] = useState(() => {
    const answers: Record<string, DeckAnswer> = {};
    for (const id of ids) {
      const value = saved[id];
      if (typeof value === "number" || typeof value === "string" || Array.isArray(value)) answers[id] = value as DeckAnswer;
    }
    const everyOneAnswered = ids.length > 0 && ids.every((id) => id in answers);
    return DeckSession.restore(ids, { index: ids.length, answers, finished: everyOneAnswered });
  });
  const [, bump] = useReducer((n: number) => n + 1, 0);

  const change = (action: () => void) => {
    action();
    bump();
  };

  return {
    deck,
    answer: (value: DeckAnswer | null) => change(() => deck.answer(value)),
    advance: () => change(() => void deck.continue()),
  };
}
