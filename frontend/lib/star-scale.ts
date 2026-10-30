/** One of the ten values of the self-rating: half a star to five stars. */
export type StarStep = {
  /** Stars times two (1 to 10): the API stores it this way, so it is never a float. */
  halves: number;
  stars: number;
  /** "2½ stars" read aloud as "2.5 stars"; one star is singular. */
  label: string;
  /** What the learner is saying about themselves, in their own voice. */
  sentence: string;
};

export type StarLevel = "beginner" | "foundation" | "proficient" | "expert";

const SENTENCES = [
  "This is completely new to me.",
  "I've heard the name, but I don't know what it means.",
  "I have a rough idea what it is, but I couldn't explain it.",
  "I know a few words and ideas, but I get lost quickly.",
  "I understand some of the basics, but I need help to use them.",
  "I know the basics and can solve simple problems.",
  "I can solve most simple problems and I am starting on harder ones.",
  "I am comfortable with it and can solve most problems on my own.",
  "I can solve hard problems and spot my own mistakes.",
  "I could explain it to someone else.",
] as const;

/**
 * The self-rating scale: ten half-star values, each with the sentence the learner sees when they pick it (approved
 * wording, docs/to_be_developed/modular-lessons-implementation-plan.md D23), and the keys that move along it. The
 * level a rating means is decided by the server; `levelOf` only says it back so the page can name it before the lesson
 * exists, and mirrors the server's table.
 */
export class StarScale {
  static readonly MIN = 1;
  static readonly MAX = 10;
  /** What the scale says before a pick is made. */
  static readonly PROMPT = "Pick the stars that fit you best.";

  static readonly STEPS: readonly StarStep[] = SENTENCES.map((sentence, index) => {
    const halves = index + 1;
    const stars = halves / 2;
    return { halves, stars, label: `${stars} ${stars === 1 ? "star" : "stars"}`, sentence };
  });

  static all(): readonly StarStep[] {
    return StarScale.STEPS;
  }

  /** The step for a number of halves, or null for anything that is not one of the ten. */
  static of(halves: number | null | undefined): StarStep | null {
    if (halves == null || !Number.isInteger(halves)) return null;
    return StarScale.STEPS[halves - 1] ?? null;
  }

  /** The sentence for a pick, or an empty string before one is made. */
  static sentence(halves: number | null | undefined): string {
    return StarScale.of(halves)?.sentence ?? "";
  }

  /** The stars the API wants (0.5 to 5) for a number of halves. */
  static starsOf(halves: number): number {
    return halves / 2;
  }

  /** Stars as the API sends them (0.5 to 5) back to halves, or null for a value that is not on the scale. */
  static halvesOf(stars: number | null | undefined): number | null {
    if (stars == null || !Number.isFinite(stars)) return null;
    const halves = stars * 2;
    return Number.isInteger(halves) && halves >= StarScale.MIN && halves <= StarScale.MAX ? halves : null;
  }

  /** The level a rating means: 0.5–1.5 Beginner, 2–3.5 Foundation, 4 Proficient, 4.5–5 Expert. */
  static levelOf(halves: number | null | undefined): StarLevel | null {
    if (StarScale.of(halves) === null) return null;
    const h = halves as number;
    if (h <= 3) return "beginner";
    if (h <= 7) return "foundation";
    return h === 8 ? "proficient" : "expert";
  }

  /**
   * Where a key moves the pick. Right and up go a half star up, left and down a half star down, Home and End to the
   * ends; nothing is picked yet, the first arrow picks the first (or last) value. Any other key returns null (the key
   * is not ours). The result stays on the scale.
   */
  static move(current: number | null, key: string): number | null {
    const up = key === "ArrowRight" || key === "ArrowUp";
    const down = key === "ArrowLeft" || key === "ArrowDown";
    if (key === "Home") return StarScale.MIN;
    if (key === "End") return StarScale.MAX;
    if (!up && !down) return null;
    if (current === null) return up ? StarScale.MIN : StarScale.MAX;
    return Math.min(StarScale.MAX, Math.max(StarScale.MIN, current + (up ? 1 : -1)));
  }

  /** Whether the pick fills the half star `slot` (1 to 10) of the row of five. */
  static fills(halves: number | null, slot: number): boolean {
    return halves !== null && slot <= halves;
  }
}
