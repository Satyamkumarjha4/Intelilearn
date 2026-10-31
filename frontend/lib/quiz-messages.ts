import { ActionRefusedMessage } from "@/lib/action-refused";
import { ApiError } from "@/lib/api";

/** What the quiz screens say when the server refuses something. The server's own words are used when they are written for learners. */
export class QuizMessages {
  static readonly MAKE = "We couldn't make that quiz. Please try again.";

  /** A refusal to make a quiz: a refused action in its own words, a field that was wrong, a busy moment, or a model that is missing. */
  static make(error: unknown): string {
    const refused = ActionRefusedMessage.of(error);
    if (refused) return refused;
    if (!(error instanceof ApiError)) return QuizMessages.MAKE;
    if (error.status === 404) return "One of those lessons isn't available any more. Pick again.";
    if (error.status === 429) return "You're going a bit fast. Wait a moment and try again.";
    if (error.status === 503) return "Quizzes aren't set up yet. Please try again later.";
    const field = Object.values(error.fields)[0]?.[0];
    return field || (error.status === 400 ? error.message : QuizMessages.MAKE);
  }

  /** A refusal to start a new try, or to make a lesson from a result. */
  static retake(error: unknown): string {
    const refused = ActionRefusedMessage.of(error);
    if (refused) return refused;
    if (error instanceof ApiError && error.status === 429) return "That's enough tries for today. You can try again tomorrow.";
    if (error instanceof ApiError && error.code === "source_missing") return "A lesson this quiz was made from has been deleted, so it can't be taken again. Make a new quiz.";
    return error instanceof ApiError ? error.message : "We couldn't start a new try. Please try again.";
  }

  static createLesson(error: unknown): string {
    const refused = ActionRefusedMessage.of(error);
    if (refused) return refused;
    if (error instanceof ApiError && error.status === 429) return "You're making lessons very fast. Wait a moment and try again.";
    return error instanceof ApiError ? error.message : "We couldn't start that lesson. Please try again.";
  }
}
