import { ActionRefusedMessage } from "@/lib/action-refused";
import { ApiError } from "@/lib/api";
import type { CreateOptions } from "@/lib/lessons-api";
import { StarScale } from "@/lib/star-scale";
import { SheetCatalog } from "@/lib/study-sheets";
import type { Entry, Intent, OfferedSheet } from "@/lib/types";

const TRY_AGAIN = "We couldn't start that lesson. Please try again.";

export type EntryChoice = { id: Entry; label: string; hint: string };
export type IntentChoice = { id: Intent; label: string; hint: string };
/** What the form picks for sheets: one of the two, or both. */
export type SheetPick = "both" | OfferedSheet;
export type SheetPickChoice = { id: SheetPick; label: string; hint: string };

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

  /** What to make: a lesson, or the study sheets alone. */
  static readonly INTENTS: readonly IntentChoice[] = [
    { id: "lesson", label: "A lesson", hint: "Pages to read, with a test at the end." },
    { id: "sheets", label: "Study sheets", hint: "Just the notes to keep: no lesson and no test." },
  ];

  /** Which sheets, when it is sheets: both is picked at first. */
  static readonly SHEET_CHOICES: readonly SheetPickChoice[] = [
    { id: "both", label: "Both", hint: "A cheat sheet and a revision sheet." },
    { id: "cheat_sheet", label: SheetCatalog.of("cheat_sheet").title, hint: SheetCatalog.of("cheat_sheet").text },
    { id: "revision_sheet", label: SheetCatalog.of("revision_sheet").title, hint: SheetCatalog.of("revision_sheet").text },
  ];

  /** The list the server takes: the cheat sheet first, as they are written. */
  static sheetsOf(pick: SheetPick): OfferedSheet[] {
    return pick === "both" ? ["cheat_sheet", "revision_sheet"] : [pick];
  }

  /** The quick check can start from two characters (not counting spaces around them); a rating also needs a pick. */
  static canStart(topic: string, busy: boolean, entry: Entry = "diagnostic", rating: number | null = null): boolean {
    if (busy || topic.trim().length < 2) return false;
    return entry !== "self_rating" || StarScale.of(rating) !== null;
  }

  static counter(topic: string): string {
    return `${Math.min(topic.length, NewLesson.TOPIC_MAX)} / ${NewLesson.TOPIC_MAX}`;
  }

  /** What to hand `lessonsApi.create` for the form as filled in. The rating is stars times two, as the scale holds it. */
  static request(
    topic: string,
    context: string,
    entry: Entry,
    rating: number | null,
    intent: Intent = "lesson",
    sheets: SheetPick = "both",
  ): { topic: string; context: string; options: CreateOptions } {
    const stars = entry === "self_rating" && rating !== null ? StarScale.starsOf(rating) : undefined;
    const options: CreateOptions = {};
    if (stars !== undefined) options.selfRating = stars;
    if (intent === "sheets") options.sheets = NewLesson.sheetsOf(sheets);
    return { topic: topic.trim(), context, options };
  }

  static intro(entry: Entry, intent: Intent = "lesson"): string {
    const made = intent === "sheets" ? "the study sheets you pick" : "a lesson";
    return entry === "self_rating"
      ? `Tell us a topic and how well you know it. We'll write ${made} that starts in the right place, with no quiz first.`
      : `Tell us a topic. We'll start with a short quick check to find out what you already know, then write ${made} that starts in the right place.`;
  }

  static steps(entry: Entry, intent: Intent = "lesson"): string[] {
    const last = intent === "sheets" ? "Your sheets" : "Your lesson";
    return entry === "self_rating" ? ["Your rating", last] : ["Quick check", "Your starting point", last];
  }

  static buttonLabel(entry: Entry, busy: boolean, intent: Intent = "lesson", sheets: SheetPick = "both"): string {
    if (busy) return "Starting…";
    if (entry !== "self_rating") return "Start my quick check";
    if (intent === "lesson") return "Start my lesson";
    return sheets === "both" ? "Make my two sheets" : SheetCatalog.makeLabel(sheets);
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
    if (error.fields.sheets) return "Pick a cheat sheet, a revision sheet, or both, then try again.";
    const field = error.fields.topic?.[0] ?? error.fields.user_context?.[0];
    return field ?? TRY_AGAIN;
  }
}
