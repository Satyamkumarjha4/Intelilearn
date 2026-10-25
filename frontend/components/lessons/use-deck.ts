"use client";

import { useMemo, useReducer, useState } from "react";

import { DeckSession, DeckStore, type DeckAnswer } from "@/lib/deck-session";

/**
 * A deck of cards with its place kept in `sessionStorage` under `storeKey`: a refresh resumes on the same card with the
 * earlier answers still locked. `clear` forgets it (after a successful submit).
 */
export function useDeck(storeKey: string, ids: string[]) {
  const store = useMemo(() => new DeckStore(storeKey), [storeKey]);
  const [deck] = useState(() => store.load(ids) ?? new DeckSession(ids));
  const [, bump] = useReducer((n: number) => n + 1, 0);

  const change = (action: () => void) => {
    action();
    store.save(deck);
    bump();
  };

  return {
    deck,
    answer: (value: DeckAnswer | null) => change(() => deck.answer(value)),
    advance: () => change(() => void deck.continue()),
    clear: () => store.clear(),
  };
}
