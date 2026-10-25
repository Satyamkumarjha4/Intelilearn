import { PATH_SLIDES, type PathId } from "@/lib/landing-content";

/** Which way a quick-check score (out of 10) sends a learner, as the landing page's carousel describes it. */
export class ScorePaths {
  static readonly TOTAL = 10;

  /** `null` for anything that is not a whole score from 0 to 10. */
  static pathFor(score: number): PathId | null {
    if (!Number.isInteger(score)) return null;
    return PATH_SLIDES.find((slide) => score >= slide.scores[0] && score <= slide.scores[1])?.id ?? null;
  }

  /** One flag per question: right (true) or not (false), right answers first. */
  static dots(score: number): boolean[] {
    return Array.from({ length: ScorePaths.TOTAL }, (_, n) => n < score);
  }
}
