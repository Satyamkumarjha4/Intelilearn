import { ActionRefusedMessage } from "@/lib/action-refused";
import { ApiError } from "@/lib/api";
import type { CreateOptions } from "@/lib/lessons-api";
import { StarScale } from "@/lib/star-scale";
import type { Entry } from "@/lib/types";

const TRY_AGAIN = "We couldn't start that lesson. Please try again.";

export type EntryChoice = { id: Entry; label: string; hint: string };

/** The rules of the "What do you want to learn?" form. */
export class NewLesson {
  static readonly TOPIC_MAX = 200;
  static readonly CONTEXT_MAX = 1000;
  static readonly EXAMPLES = ["Binary search", "Photosynthesis", "Quadratic equations", "The French Revolution", "Newton's laws", "Python loops"];

  /** The two ways to say where you are: answer a few questions, or say it yourself. */
  static readonly ENTRIES: readonly EntryChoice[] = [
    { id: "diagnostic", label: "Take a quick check", hint: "Answer a few short questions and we'll find your level." },
    { id: "self_rating", label: "Rate yourself", hint: "Tell us how well you know it and go straight to your lesson." },
  ];

  /** The quick check can start from two characters (not counting spaces around them); a rating also needs a pick. */
  static canStart(topic: string, busy: boolean, entry: Entry = "diagnostic", rating: number | null = null): boolean {
    if (busy || topic.trim().length < 2) return false;
    return entry !== "self_rating" || StarScale.of(rating) !== null;
  }

  static counter(topic: string): string {
    return `${Math.min(topic.length, NewLesson.TOPIC_MAX)} / ${NewLesson.TOPIC_MAX}`;
  }

  /** What to hand `lessonsApi.create` for the form as filled in. The rating is stars times two, as the scale holds it. */
  static request(topic: string, context: string, entry: Entry, rating: number | null): { topic: string; context: string; options: CreateOptions } {
    const stars = entry === "self_rating" && rating !== null ? StarScale.starsOf(rating) : undefined;
    return { topic: topic.trim(), context, options: stars === undefined ? {} : { selfRating: stars } };
  }

  static intro(entry: Entry): string {
    return entry === "self_rating"
      ? "Tell us a topic and how well you know it. We'll build a lesson that starts in the right place, with no quiz first."
      : "Tell us a topic. We'll start with a short quick check to find out what you already know, then build a lesson that starts in the right place.";
  }

  static steps(entry: Entry): string[] {
    return entry === "self_rating" ? ["Your rating", "Your lesson"] : ["Quick check", "Your starting point", "Your lesson"];
  }

  static buttonLabel(entry: Entry, busy: boolean): string {
    if (busy) return "Starting…";
    return entry === "self_rating" ? "Start my lesson" : "Start my quick check";
  }

  /** Why a start was refused, in words that say what to do. */
  static errorMessage(error: unknown): string {
    const refused = ActionRefusedMessage.of(error);
    if (refused) return refused;
    if (!(error instanceof ApiError)) return TRY_AGAIN;
    if (error.code === "llm_not_configured") return "Lesson building is switched off right now. Please try again later.";
    if (error.code === "queue_unavailable") return "We couldn't reach our helper just now. Nothing was lost: please try again in a minute.";
    if (error.status === 429) return "You've started a lot of lessons just now. Please wait a little while, then try again.";
    if (error.fields.self_rating) return "Pick the stars that fit you best, then try again.";
    const field = error.fields.topic?.[0] ?? error.fields.user_context?.[0];
    return field ?? TRY_AGAIN;
  }
}
