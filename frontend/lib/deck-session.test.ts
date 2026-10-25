/**
 * Unit under test: `DeckSession` and `DeckStore`, the state behind the flashcard deck (quick check and final test).
 *
 * Why: the deck promises that an answer locks when the learner continues and that there is no way back. If the state
 * allowed a step back, an unanswered card to be skipped, or a refresh to forget locked answers (or to unlock them),
 * the promise on the card would be false, and for the one-attempt test that matters.
 *
 * Use cases:
 * - starts on the first card with nothing answered; a deck without cards is already finished
 * - the current card can be answered and re-answered until the learner continues; an answer for any other card, or an
 *   option that is not text, a number or "I don't know", is refused
 * - a blank text answer, or none (null), leaves the card unanswered; "I don't know" and option 0 are answers
 * - continuing needs an answer, locks the card and moves on; there is no way back
 * - continuing on the last card finishes the deck, and nothing can be answered after that
 * - the payload is every answer, only once finished
 * - the progress segments are done, current and todo, and a finished deck is all done
 * - a snapshot restores the place and the locked answers; a snapshot that does not fit the deck is mended, never
 *   trusted (unknown ids dropped, a place past an unanswered card pulled back to it)
 * - the store keeps a snapshot per key, forgets it on clear, and works without storage, with broken storage, and with
 *   rubbish in it
 */
import { describe, expect, test } from "bun:test";

import { DeckSession, DeckStore, DONT_KNOW } from "./deck-session";

const ids = ["a", "b", "c"];

describe("DeckSession", () => {
  test("starts on the first card with nothing answered", () => {
    const deck = new DeckSession(ids);

    expect([deck.current, deck.index, deck.total, deck.answeredCount, deck.canContinue, deck.finished]).toEqual(["a", 0, 3, 0, false, false]);
    expect(deck.isLast).toBe(false);
  });

  test("a deck without cards is already finished", () => {
    const deck = new DeckSession([]);

    expect([deck.current, deck.finished, deck.canContinue]).toEqual([undefined, true, false]);
    expect(deck.payload()).toEqual({});
  });

  test("the current card can be answered and answered again until the learner continues", () => {
    const deck = new DeckSession(ids);
    deck.answer(2);
    deck.answer(1);

    expect(deck.answerOf("a")).toBe(1);
    expect(deck.canContinue).toBe(true);
  });

  test.each([[0], [DONT_KNOW], ["some text"]])("%p is an answer", (value) => {
    const deck = new DeckSession(ids);
    deck.answer(value);

    expect(deck.canContinue).toBe(true);
  });

  test.each([[null], [""], ["   \n"]])("%p leaves the card unanswered, and clears an earlier answer", (blank) => {
    const deck = new DeckSession(ids);
    deck.answer("x");
    deck.answer(blank);

    expect([deck.answerOf("a"), deck.canContinue, deck.answeredCount]).toEqual([undefined, false, 0]);
  });

  test("refuses an answer that is not an option, a number or text", () => {
    const deck = new DeckSession(ids);

    expect(() => deck.answer(-1)).toThrow(RangeError);
    expect(() => deck.answer(1.5)).toThrow(RangeError);
    expect(() => deck.answer(Number.NaN)).toThrow(RangeError);
    expect(() => deck.answer({} as never)).toThrow(RangeError);
  });

  test("continuing needs an answer, locks the card and moves on", () => {
    const deck = new DeckSession(ids);

    expect(deck.continue()).toBe(false);
    expect(deck.index).toBe(0);
    deck.answer(3);
    expect(deck.continue()).toBe(true);
    expect([deck.current, deck.index, deck.isLocked("a"), deck.isLocked("b")]).toEqual(["b", 1, true, false]);
  });

  test("a locked card cannot be answered again, and there is no way back", () => {
    const deck = new DeckSession(ids);
    deck.answer(3);
    deck.continue();
    deck.answer(0);

    expect(deck.answerOf("a")).toBe(3);
    expect(deck.answerOf("b")).toBe(0);
    expect("back" in deck || "prev" in deck || "previous" in deck).toBe(false);
  });

  test("continuing on the last card finishes the deck, and nothing can be answered after that", () => {
    const deck = new DeckSession(["a", "b"]);
    deck.answer(0);
    deck.continue();
    deck.answer("done");
    expect(deck.isLast).toBe(true);
    expect(deck.continue()).toBe(true);

    expect([deck.finished, deck.current, deck.canContinue]).toEqual([true, undefined, false]);
    expect(deck.continue()).toBe(false);
    deck.answer("again");
    expect(deck.answerOf("b")).toBe("done");
  });

  test("the payload is every answer, only once finished", () => {
    const deck = new DeckSession(["a", "b"]);
    deck.answer(1);
    deck.continue();
    deck.answer(DONT_KNOW);
    expect(() => deck.payload()).toThrow("Answer every question");
    deck.continue();

    expect(deck.payload()).toEqual({ a: 1, b: DONT_KNOW });
  });

  test("the progress segments are done, current and todo", () => {
    const deck = new DeckSession(ids);
    expect(deck.segments).toEqual(["current", "todo", "todo"]);
    deck.answer(0);
    deck.continue();
    expect(deck.segments).toEqual(["done", "current", "todo"]);
    deck.answer(0);
    deck.continue();
    deck.answer(0);
    deck.continue();
    expect(deck.segments).toEqual(["done", "done", "done"]);
  });
});

describe("snapshots", () => {
  const played = () => {
    const deck = new DeckSession(ids);
    deck.answer(2);
    deck.continue();
    deck.answer("half way");
    return deck;
  };

  test("restore the place, the locked answers and the answer on the current card", () => {
    const back = DeckSession.restore(ids, played().snapshot());

    expect([back.index, back.answerOf("a"), back.answerOf("b"), back.isLocked("a"), back.isLocked("b")]).toEqual([1, 2, "half way", true, false]);
  });

  test("restore a finished deck", () => {
    const deck = new DeckSession(["a"]);
    deck.answer(1);
    deck.continue();

    expect(DeckSession.restore(["a"], deck.snapshot()).finished).toBe(true);
  });

  test("a place past an unanswered card is pulled back to it", () => {
    const back = DeckSession.restore(ids, { index: 2, answers: { a: 1 }, finished: false });

    expect(back.index).toBe(1);
  });

  test("a finished snapshot with a missing answer is not finished", () => {
    const back = DeckSession.restore(ids, { index: 3, answers: { a: 1, c: 1 }, finished: true });

    expect([back.finished, back.index]).toEqual([false, 1]);
  });

  test("unknown ids, blank answers and odd values are dropped, and a place out of range is clamped", () => {
    const back = DeckSession.restore(ids, { index: 99, answers: { a: 0, ghost: 1, b: "  ", c: { x: 1 } as never }, finished: false });

    expect([back.index, back.answerOf("a"), back.answerOf("b"), back.answerOf("c"), back.answeredCount]).toEqual([1, 0, undefined, undefined, 1]);
    expect(DeckSession.restore(ids, { index: -5, answers: {}, finished: false }).index).toBe(0);
  });
});

describe("DeckStore", () => {
  const memory = () => {
    const data: Record<string, string> = {};
    return { data, getItem: (k: string) => data[k] ?? null, setItem: (k: string, v: string) => void (data[k] = v), removeItem: (k: string) => void delete data[k] };
  };

  test("keeps a snapshot per key and forgets it on clear", () => {
    const storage = memory();
    const deck = new DeckSession(ids);
    deck.answer(1);
    new DeckStore("L1:diagnostic", storage).save(deck);

    expect(new DeckStore("L1:diagnostic", storage).load(ids)?.answerOf("a")).toBe(1);
    expect(new DeckStore("L1:test", storage).load(ids)).toBeNull();
    new DeckStore("L1:diagnostic", storage).clear();
    expect(new DeckStore("L1:diagnostic", storage).load(ids)).toBeNull();
  });

  test.each([["not json"], ["[1,2]"], ['{"index":"x"}'], ["null"]])("rubbish (%s) is no snapshot", (raw) => {
    const storage = memory();
    storage.setItem("deck:K", raw);

    expect(new DeckStore("K", storage).load(ids)).toBeNull();
  });

  test("works without storage and with storage that throws", () => {
    const broken = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("full");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    };
    for (const storage of [null, broken]) {
      const store = new DeckStore("K", storage);
      expect(store.load(ids)).toBeNull();
      expect(() => store.save(new DeckSession(ids))).not.toThrow();
      expect(() => store.clear()).not.toThrow();
    }
  });
});
