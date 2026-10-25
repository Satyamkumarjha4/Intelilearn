import { HERO_FALLBACK_QUESTION } from "@/lib/landing-content";
import type { DemoOutcome, DemoQuestion } from "@/lib/types";

const OPTIONS = 3;
const BANDS = 5;
const BAND_NAMES = ["", "Basics", "Easy", "Medium", "Hard", "Expert"];

const text = (value: unknown): string => (typeof value === "string" ? value.trim() : "");
const whole = (value: unknown, min: number, max: number): value is number => typeof value === "number" && Number.isInteger(value) && value >= min && value <= max;
const record = (value: unknown): Record<string, unknown> | null => (value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null);

/** Reading, labelling and the built-in version of the landing page's try-it question. */
export class DemoQuestions {
  /**
   * The API's question, or null if it is not a question the card can show. The answer comes from a table that people
   * edit by hand, so nothing is taken on trust: three options, an answer among them, a band, both outcomes.
   */
  static parse(raw: unknown): DemoQuestion | null {
    const data = record(raw);
    if (!data || !whole(data.id, 0, Number.MAX_SAFE_INTEGER) || !whole(data.band, 1, BANDS)) return null;
    const options = Array.isArray(data.options) ? data.options.map(text) : [];
    if (options.length !== OPTIONS || options.some((option) => option === "") || !whole(data.correct_index, 0, OPTIONS - 1)) return null;
    const right = DemoQuestions.outcome(data.outcome_right);
    const wrong = DemoQuestions.outcome(data.outcome_wrong);
    const [subject, level_label, question] = [text(data.subject), text(data.level_label), text(data.question)];
    if (!right || !wrong || !subject || !level_label || !question) return null;
    return { id: data.id, subject, level_label, band: data.band, question, options, correct_index: data.correct_index, outcome_right: right, outcome_wrong: wrong };
  }

  /** "Medium · Physics · Class 9", the line over the question. */
  static label(question: DemoQuestion): string {
    return [BAND_NAMES[question.band], question.subject, question.level_label].join(" · ");
  }

  /** The built-in question, for when the API has none. Its id (0) is one no stored question has. */
  static fallback(): DemoQuestion {
    return HERO_FALLBACK_QUESTION;
  }

  /** What to show after asking for another question failed: the built-in one, unless that is the one just seen. */
  static afterFailure(seenId: number): DemoQuestion | null {
    return seenId === HERO_FALLBACK_QUESTION.id ? null : HERO_FALLBACK_QUESTION;
  }

  private static outcome(raw: unknown): DemoOutcome | null {
    const data = record(raw);
    if (!data || !whole(data.level, 1, BANDS)) return null;
    const [level_label, lesson_start] = [text(data.level_label), text(data.lesson_start)];
    return level_label && lesson_start ? { level: data.level, level_label, lesson_start } : null;
  }
}

export type AskOptions = {
  /** The id of the question just seen, so it does not come back. */
  exclude?: number;
  /** The visitor's address, when the server asks on their behalf (so the API's limit is theirs, not the server's). */
  clientIp?: string;
};

/** Asks the API for a random question. Never throws: anything that goes wrong is `null`, and the caller picks the fallback. */
export class DemoQuestionFetcher {
  static readonly PATH = "/api/landing/demo-question";

  constructor(
    private readonly fetcher: typeof fetch = ((...args: Parameters<typeof fetch>) => fetch(...args)) as typeof fetch,
    /** The API's origin; empty in the browser, which goes through this site's own `/api`. */
    private readonly base = "",
    private readonly timeoutMs = 1500,
  ) {}

  /** On the Next server: straight to Django, the way the `/api` proxy reaches it. */
  static forServer(): DemoQuestionFetcher {
    return new DemoQuestionFetcher(undefined, process.env.DJANGO_API_ORIGIN ?? `http://localhost:${process.env.BACKEND_PORT ?? "8000"}`);
  }

  async fetch({ exclude, clientIp }: AskOptions = {}): Promise<DemoQuestion | null> {
    const query = exclude === undefined ? "" : `?exclude=${exclude}`;
    try {
      const response = await this.fetcher(`${this.base}${DemoQuestionFetcher.PATH}${query}`, {
        cache: "no-store",
        signal: AbortSignal.timeout(this.timeoutMs),
        ...(clientIp ? { headers: { "x-forwarded-for": clientIp } } : {}),
      });
      return response.ok ? DemoQuestions.parse(await response.json()) : null;
    } catch {
      return null;
    }
  }
}
