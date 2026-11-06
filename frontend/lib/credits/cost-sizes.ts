import type { Entry, FollowupLevel, Intent, MasteryPick, QuizCreateRequest } from "@/lib/types";

/** What to ask the quote endpoint: an action and the hints the service sends with it. The server does the pricing. */
export type CostAsk = { action: string; size: Record<string, unknown> };

/**
 * The hints for each screen that starts paid work, the same ones the services send (docs/reference/api.md, "Credits").
 * A screen builds the ask and shows what the server answers; it never works out a price itself, so the number on a button is
 * the number the gate will charge.
 */
export class CostSizes {
  /** A new lesson from the form: how the level is found, what to make, how many sheets, and whether it was recommended. */
  static newLesson(entry: Entry, intent: Intent, sheets: number, origin: "direct" | "recommendation" | "quiz_result" = "direct"): CostAsk {
    const size: Record<string, unknown> = { entry, intent, origin, covers: entry === "diagnostic" ? "diagnostic" : "all" };
    if (intent === "sheets") {
      size.sheets = sheets;
      size.grounding = entry === "diagnostic" ? "quiz" : "none";
    }
    return { action: "lesson.create", size };
  }

  /** "Make a lesson on this": a topic from a test result is a recommended lesson, found by a Quick check. */
  static lessonOnThis(): CostAsk {
    return CostSizes.newLesson("diagnostic", "lesson", 0, "recommendation");
  }

  /** "Create a lesson for this": a lesson from a quick quiz result. */
  static lessonFromQuiz(): CostAsk {
    return CostSizes.newLesson("quiz_result", "lesson", 0, "quiz_result");
  }

  /** The choice after a perfect Quick check. */
  static mastery(pick: MasteryPick): CostAsk {
    const size = pick === "lesson" ? { choice: "lesson", perfect: true } : { choice: "sheets_only", perfect: true, sheets: 2, grounding: "quiz" };
    return { action: "lesson.continue", size };
  }

  static followup(level: FollowupLevel): CostAsk {
    return {
      action: "lesson.followup",
      size: { entry: "followup", intent: "lesson", origin: "followup", covers: "all", followup_level: level },
    };
  }

  /** Attempt 2 onward; attempt 1 is part of the lesson and costs nothing. */
  static testRetake(attemptNo: number): CostAsk {
    return { action: "test.retake", size: { question_count: 10, attempt_no: Math.max(2, attemptNo) } };
  }

  /** Sheets added to a lesson: `grounding` is what they rest on ("lesson" when the lesson has pages). */
  static sheets(count: number, grounding: "lesson" | "quiz" | "none"): CostAsk {
    return { action: "sheet.generate", size: { sheets: count, grounding } };
  }

  /** A new quick quiz as the wizard has it: the count, where the questions come from, and how the level is found. */
  static quiz(request: Pick<QuizCreateRequest, "num_questions" | "source" | "level">): CostAsk {
    const lessons = request.source.type === "lessons" ? request.source.lesson_ids.length : 0;
    return {
      action: "quiz.create",
      size: { num_questions: request.num_questions, source_type: request.source.type, sources: lessons, level_mode: request.level.mode },
    };
  }

  static quizRetake(numQuestions: number, sourceType: "topic" | "lessons"): CostAsk {
    return { action: "quiz.retake", size: { num_questions: numQuestions, source_type: sourceType } };
  }
}
