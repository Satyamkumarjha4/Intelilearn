import { ActionRefusedMessage } from "@/lib/action-refused";
import { ApiError } from "@/lib/api";
import type { LessonDetail, MasteryPick } from "@/lib/types";

export type MasteryOption = {
  pick: MasteryPick;
  /** The words on the card: they are the product's, word for word. */
  title: string;
  text: string;
  bullets: [string, string];
  /** A rough guess at the time it takes, in the words of a card. */
  time: string;
};

const OPTIONS: MasteryOption[] = [
  {
    pick: "lesson",
    title: "Continue with an Expert lesson",
    text: "A full lesson pitched at your level, with a test at the end.",
    bullets: ["Goes straight to the hard parts", "Includes a test you can retake"],
    time: "A few minutes to build",
  },
  {
    pick: "sheets",
    title: "Cheat sheet + revision sheet only",
    text: "Two sheets to revise from. No lesson and no test.",
    bullets: ["The essentials on one or two pages", "Every subtopic in short notes"],
    time: "About 12 min to read",
  },
];

/**
 * The choice a learner gets after a perfect quick check: carry on with an Expert lesson, or take two study sheets and
 * stop. A lesson that was already waiting at the older three-sheet choice keeps showing those cards (`legacy`), so
 * nobody finds the options changed under them.
 */
export class MasteryOptions {
  static readonly DEFAULT: MasteryPick = "lesson";

  static all(): MasteryOption[] {
    return OPTIONS;
  }

  static of(pick: MasteryPick): MasteryOption {
    return OPTIONS.find((option) => option.pick === pick)!;
  }

  /** The old three-sheet cards, for a lesson that was waiting at them. */
  static legacy(lesson: Pick<LessonDetail, "mastery_options">): boolean {
    return lesson.mastery_options === "three_sheets";
  }

  /** The button follows the card picked. */
  static buttonLabel(pick: MasteryPick, busy: boolean): string {
    if (busy) return "Starting…";
    return pick === "lesson" ? "Start my Expert lesson" : "Make my two sheets";
  }

  /** Why the pick did not go through, in words that say what to do: a refusal in its own words. */
  static errorMessage(error: unknown): string {
    const refused = ActionRefusedMessage.of(error);
    if (refused) return refused;
    if (error instanceof ApiError && error.status === 409) return "That choice was already made. Reloading shows where your lesson is.";
    return "We couldn't start that. Please try again.";
  }
}
