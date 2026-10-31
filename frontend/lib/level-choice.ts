import { StarScale } from "@/lib/star-scale";
import type { LevelMode, QuizLevelRequest } from "@/lib/types";

export type LevelOption = { id: LevelMode; label: string; hint: string };
export type LevelSource = "topic" | "lessons";

/** How a quiz finds the level it is written at, and the one the wizard starts on (decision D21). */
export class LevelChoice {
  static readonly OPTIONS: readonly LevelOption[] = [
    { id: "existing_score", label: "Use my test scores", hint: "Each lesson's questions follow how you did on its test." },
    { id: "self_rating", label: "Rate yourself", hint: "Tell us how well you know it." },
    { id: "calibration", label: "A quick warm-up", hint: "Five questions that find your level, each a little harder or easier." },
  ];

  /**
   * The modes to show. Scores only make sense for lessons; everything else is always on offer, because the learner can
   * pick any way to find their level.
   */
  static options(source: LevelSource): LevelOption[] {
    return LevelChoice.OPTIONS.filter((option) => option.id !== "existing_score" || source === "lessons");
  }

  /**
   * Where the wizard starts: the scores when every lesson picked has a graded test, else the learner's own rating.
   * `scored` says, for each lesson picked, whether it has a score.
   */
  static defaultMode(source: LevelSource, scored: readonly boolean[]): LevelMode {
    return source === "lessons" && scored.length > 0 && scored.every(Boolean) ? "existing_score" : "self_rating";
  }

  /** Why a mode cannot be used right now, in words, or null when it can. */
  static unavailable(mode: LevelMode, source: LevelSource, scored: readonly boolean[]): string | null {
    if (mode !== "existing_score") return null;
    if (source !== "lessons") return "Scores belong to lessons.";
    return scored.every(Boolean) ? null : "Some of these lessons haven't had a test yet.";
  }

  /** Whether the pick is complete: a rating needs its stars. */
  static ready(mode: LevelMode, rating: number | null): boolean {
    return mode !== "self_rating" || StarScale.of(rating) !== null;
  }

  /** What the server is sent, or null while the pick is not complete. The rating is stars times two as the scale holds it. */
  static request(mode: LevelMode, rating: number | null): QuizLevelRequest | null {
    if (!LevelChoice.ready(mode, rating)) return null;
    return mode === "self_rating" ? { mode, rating: StarScale.starsOf(rating as number) } : { mode };
  }

  static label(mode: LevelMode): string {
    return LevelChoice.OPTIONS.find((option) => option.id === mode)?.label ?? mode;
  }
}
