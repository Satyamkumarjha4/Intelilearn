import { BAND_LABELS, BAND_ORDER } from "@/lib/stage-view";
import type { Assessment, Band, QuizResultSummary, ReviewQuestion } from "@/lib/types";

export type Dot = "right" | "wrong" | "unsure";
export type BandView = { band: Band; label: string; dots: Dot[] };
export type StartingPointView = {
  level: { filled: number; total: number; label: string };
  bands: BandView[];
  known: string[];
  gaps: string[];
  startPoint: string;
  confidence: { fraction: number; label: string };
};

const LEVELS: Record<string, [number, string]> = {
  novice: [1, "New to it"],
  beginner: [2, "Finding your feet"],
  intermediate: [3, "Getting comfortable"],
  advanced: [4, "Confident"],
  expert: [5, "Expert"],
};
const CONFIDENCE: Record<string, [number, string]> = {
  low: [1 / 3, "Still getting to know you"],
  medium: [2 / 3, "Fairly sure"],
  high: [1, "Very sure"],
};

/** What the "Your starting point" card shows, from the assessment and the quick check (docs/frontend.md). */
export class StartingPoint {
  static readonly SEGMENTS = 5;

  /** `review` is optional: it tells "I don't know" from a wrong answer, which the score alone cannot. */
  static of(
    assessment: Assessment,
    result: QuizResultSummary | null,
    review?: { questions: ReviewQuestion[] } | null,
  ): StartingPointView {
    const word = assessment.level.trim().toLowerCase();
    const [filled, label] = LEVELS[word] ?? [0, word.charAt(0).toUpperCase() + word.slice(1)];
    const [fraction, sure] = CONFIDENCE[assessment.confidence] ?? CONFIDENCE.low;
    return {
      level: { filled, total: StartingPoint.SEGMENTS, label },
      bands: result ? StartingPoint.bands(result, review) : [],
      known: assessment.known_concepts,
      gaps: assessment.gaps,
      startPoint: assessment.start_point,
      confidence: { fraction, label: sure },
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
