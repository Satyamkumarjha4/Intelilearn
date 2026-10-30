import { BAND_LABELS, BAND_ORDER } from "@/lib/stage-view";
import { StarScale } from "@/lib/star-scale";
import type { Assessment, Band, QuizResultSummary, ReviewQuestion } from "@/lib/types";

export type Dot = "right" | "wrong" | "unsure";
export type BandView = { band: Band; label: string; dots: Dot[] };
export type StartingPointView = {
  level: { filled: number; total: number; label: string };
  bands: BandView[];
  known: string[];
  gaps: string[];
  startPoint: string;
  /** How sure we are of the level; none for a learner who rated themselves, because nothing was tested. */
  confidence: { fraction: number; label: string } | null;
  /** What a learner who rated themselves said: the stars and their own sentence. Null for everyone else. */
  rating: { halves: number; label: string; sentence: string } | null;
};

/** The four levels (beginner, foundation, proficient, expert). The API only sends these names. */
const LEVELS: Record<string, [number, string]> = {
  beginner: [1, "New to it"],
  foundation: [2, "Finding your feet"],
  proficient: [3, "Getting comfortable"],
  expert: [4, "Expert"],
};
const CONFIDENCE: Record<string, [number, string]> = {
  low: [1 / 3, "Still getting to know you"],
  medium: [2 / 3, "Fairly sure"],
  high: [1, "Very sure"],
};

/** What the "Your starting point" card shows, from the assessment and the quick check (docs/reference/frontend.md). */
export class StartingPoint {
  static readonly SEGMENTS = 4;

  /** `review` is optional: it tells "I don't know" from a wrong answer, which the score alone cannot. `stars` is the
   *  rating of a self-rated lesson (0.5 to 5), whose card shows the level and the stars instead of the quiz. */
  static of(
    assessment: Assessment,
    result: QuizResultSummary | null,
    review?: { questions: ReviewQuestion[] } | null,
    stars?: number | null,
  ): StartingPointView {
    const word = assessment.level.trim().toLowerCase();
    const [filled, label] = LEVELS[word] ?? [0, word.charAt(0).toUpperCase() + word.slice(1)];
    const [fraction, sure] = CONFIDENCE[assessment.confidence] ?? CONFIDENCE.low;
    const step = StarScale.of(StarScale.halvesOf(stars));
    const rated = assessment.source === "self_rating" || step !== null;
    return {
      level: { filled, total: StartingPoint.SEGMENTS, label },
      bands: result ? StartingPoint.bands(result, review) : [],
      known: assessment.known_concepts,
      gaps: assessment.gaps,
      startPoint: assessment.start_point,
      confidence: rated ? null : { fraction, label: sure },
      rating: step ? { halves: step.halves, label: step.label, sentence: step.sentence } : null,
    };
  }

  /** The dots of each band the quick check asked, easiest first. */
  static bands(result: QuizResultSummary, review?: { questions: ReviewQuestion[] } | null): BandView[] {
    return BAND_ORDER.flatMap((band) => {
      const score = result.by_band[band];
      if (!score) return [];
      const asked = review?.questions.filter((q) => q.band === band) ?? [];
      const dots = asked.length ? asked.map(StartingPoint.dotOf) : StartingPoint.dotsOf(score);
      return [{ band, label: BAND_LABELS[band], dots }];
    });
  }

  private static dotOf(question: ReviewQuestion): Dot {
    return question.answer === "dont_know" ? "unsure" : question.correct ? "right" : "wrong";
  }

  private static dotsOf([right, total]: [number, number]): Dot[] {
    return Array.from({ length: total }, (_, n): Dot => (n < right ? "right" : "wrong"));
  }
}
