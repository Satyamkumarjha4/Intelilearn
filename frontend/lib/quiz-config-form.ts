import { LevelChoice, type LevelSource } from "@/lib/level-choice";
import { QuestionTypeCatalog, type TopicKinds } from "@/lib/question-type-catalog";
import type { LessonSummary, LevelMode, QuizCreateRequest, QuizQuestionType } from "@/lib/types";

/** A lesson a quiz can be made from, as the wizard lists it. */
export type EligibleLesson = { id: string; title: string; level: string; scored: boolean; created: string };

export type WizardStep = "source" | "count" | "kinds" | "level";

export type QuizFormState = {
  source: LevelSource;
  topic: string;
  lessonIds: string[];
  count: number;
  types: QuizQuestionType[];
  /** Null until the learner picks (or the wizard's own start applies). */
  mode: LevelMode | null;
  /** The self-rating in halves (1 to 10), as `StarScale` holds it. */
  rating: number | null;
};

/**
 * The rules of the "New quick quiz" wizard (docs: plan §11.4, D17, D18). The counts are the presets 5 to 30, and those
 * below the number of lessons picked are hidden; at most ten lessons can be picked; short and written answers are hidden
 * below ten questions. The server enforces every one of these; the form only keeps the learner from asking for what it
 * would refuse.
 */
export class QuizConfigForm {
  static readonly COUNTS = [5, 10, 15, 20, 25, 30] as const;
  static readonly DEFAULT_COUNT = 10;
  static readonly MAX_LESSONS = 10;
  static readonly TOPIC_MIN = 2;
  static readonly TOPIC_MAX = 200;
  static readonly STEPS: readonly WizardStep[] = ["source", "count", "kinds", "level"];

  static initial(): QuizFormState {
    return { source: "topic", topic: "", lessonIds: [], count: QuizConfigForm.DEFAULT_COUNT, types: ["mcq"], mode: null, rating: null };
  }

  // --- the source ----------------------------------------------------------------------------------------------

  /** The lessons a quiz can be made from: ready, with pages (not study sheets only), newest first. */
  static eligible(lessons: readonly LessonSummary[]): EligibleLesson[] {
    return lessons
      .filter((lesson) => lesson.stage === "ready" && lesson.intent === "lesson" && !lesson.sheets_only)
      .map((lesson) => ({
        id: lesson.id,
        title: lesson.title || lesson.topic,
        level: lesson.level,
        scored: lesson.latest_score !== null,
        created: lesson.created_at,
      }))
      .sort((a, b) => b.created.localeCompare(a.created));
  }

  static setSource(state: QuizFormState, source: LevelSource): QuizFormState {
    return QuizConfigForm.settle({ ...state, source, mode: null });
  }

  /** Picks or drops a lesson. Past the limit nothing is added. The count is raised if the lessons outgrow it. */
  static toggleLesson(state: QuizFormState, id: string): QuizFormState {
    const picked = state.lessonIds.includes(id);
    if (!picked && state.lessonIds.length >= QuizConfigForm.MAX_LESSONS) return state;
    const lessonIds = picked ? state.lessonIds.filter((one) => one !== id) : [...state.lessonIds, id];
    return QuizConfigForm.settle({ ...state, lessonIds });
  }

  static canAddLesson(state: QuizFormState, id: string): boolean {
    return state.lessonIds.includes(id) || state.lessonIds.length < QuizConfigForm.MAX_LESSONS;
  }

  // --- the count -----------------------------------------------------------------------------------------------

  /** The counts to show: the presets, and not those below the number of lessons (each must add a question). */
  static counts(state: Pick<QuizFormState, "source" | "lessonIds">): number[] {
    const floor = state.source === "lessons" ? state.lessonIds.length : 0;
    return QuizConfigForm.COUNTS.filter((count) => count >= floor);
  }

  static setCount(state: QuizFormState, count: number, kinds: TopicKinds = null): QuizFormState {
    const allowed = QuizConfigForm.counts(state);
    const chosen = allowed.includes(count as never) ? count : (allowed[0] ?? QuizConfigForm.COUNTS[0]);
    return { ...state, count: chosen, types: QuestionTypeCatalog.keep(state.types, kinds, chosen) };
  }

  // --- the kinds -----------------------------------------------------------------------------------------------

  static toggleKind(state: QuizFormState, id: QuizQuestionType): QuizFormState {
    return { ...state, types: QuestionTypeCatalog.toggle(state.types, id) };
  }

  /** The kinds for the topic the learner typed (or the lessons they picked, which are never judged: all are offered). */
  static kindsFor(state: QuizFormState, judged: TopicKinds): TopicKinds {
    return state.source === "topic" ? judged : null;
  }

  // --- the level -----------------------------------------------------------------------------------------------

  /** The mode in force: the learner's pick, else where the wizard starts for these lessons. */
  static modeOf(state: QuizFormState, lessons: readonly EligibleLesson[]): LevelMode {
    return state.mode ?? LevelChoice.defaultMode(state.source, QuizConfigForm.scores(state, lessons));
  }

  /** Whether each picked lesson has a graded test, in the order picked. */
  static scores(state: QuizFormState, lessons: readonly EligibleLesson[]): boolean[] {
    if (state.source !== "lessons") return [];
    return state.lessonIds.map((id) => lessons.find((lesson) => lesson.id === id)?.scored ?? false);
  }

  static setMode(state: QuizFormState, mode: LevelMode): QuizFormState {
    return { ...state, mode };
  }

  static setRating(state: QuizFormState, rating: number | null): QuizFormState {
    return { ...state, rating };
  }

  // --- the whole form ------------------------------------------------------------------------------------------

  /** Whether the learner can move on from a step. */
  static stepReady(step: WizardStep, state: QuizFormState, lessons: readonly EligibleLesson[]): boolean {
    switch (step) {
      case "source":
        return state.source === "topic"
          ? state.topic.trim().length >= QuizConfigForm.TOPIC_MIN
          : state.lessonIds.length >= 1 && state.lessonIds.length <= QuizConfigForm.MAX_LESSONS;
      case "count":
        return QuizConfigForm.counts(state).includes(state.count as never);
      case "kinds":
        return state.types.length > 0;
      case "level": {
        const mode = QuizConfigForm.modeOf(state, lessons);
        const blocked = LevelChoice.unavailable(mode, state.source, QuizConfigForm.scores(state, lessons));
        return blocked === null && LevelChoice.ready(mode, state.rating);
      }
    }
  }

  static ready(state: QuizFormState, lessons: readonly EligibleLesson[]): boolean {
    return QuizConfigForm.STEPS.every((step) => QuizConfigForm.stepReady(step, state, lessons));
  }

  /** What the server is sent, or null while the form is not complete. */
  static request(state: QuizFormState, lessons: readonly EligibleLesson[]): QuizCreateRequest | null {
    if (!QuizConfigForm.ready(state, lessons)) return null;
    const level = LevelChoice.request(QuizConfigForm.modeOf(state, lessons), state.rating);
    if (level === null) return null;
    return {
      source: state.source === "topic" ? { type: "topic", topic: state.topic.trim() } : { type: "lessons", lesson_ids: state.lessonIds },
      num_questions: state.count,
      types: state.types,
      level,
    };
  }

  /** Keeps the count and the kinds valid after the source changed. */
  private static settle(state: QuizFormState): QuizFormState {
    return QuizConfigForm.setCount(state, state.count);
  }
}
