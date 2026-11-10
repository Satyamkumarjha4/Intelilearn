import type { PublicPricing, PublicTestimonial } from "@/lib/landing/types";

export type ReadOptions = {
  /** The visitor's address, when the server reads on their behalf (so the API's limit is theirs, not the server's). */
  clientIp?: string;
};

const record = (value: unknown): Record<string, unknown> | null => (value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null);
const text = (value: unknown): string => (typeof value === "string" ? value.trim() : "");
const count = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0;
const maybeCount = (value: unknown): value is number | null => value === null || count(value);
const maybeRange = (value: unknown): boolean => value === null || (!!record(value) && count(record(value)?.min) && count(record(value)?.max));

/**
 * Reads the two public endpoints for the landing page, on the Next server. Never throws: a testimonial list that cannot be
 * read is an empty one (the page then shows the maker's note), and a price list that cannot be read is `null` (the page
 * then shows no number at all), so the front page always loads. The answers are never cached here, because a change made
 * in the console must show on the next load (the API keeps its own one-minute cache, cleared by every change).
 */
export class PublicLanding {
  static readonly TESTIMONIALS = "/api/public/testimonials";
  static readonly PRICING = "/api/public/pricing";

  constructor(
    private readonly fetcher: typeof fetch = ((...args: Parameters<typeof fetch>) => fetch(...args)) as typeof fetch,
    private readonly base = "",
    private readonly timeoutMs = 2500,
  ) {}

  /** On the Next server: straight to Django, the way the `/api` proxy reaches it. */
  static forServer(): PublicLanding {
    return new PublicLanding(undefined, process.env.DJANGO_API_ORIGIN ?? `http://localhost:${process.env.BACKEND_PORT ?? "8000"}`);
  }

  async testimonials(options: ReadOptions = {}): Promise<PublicTestimonial[]> {
    const body = record(await this.read(PublicLanding.TESTIMONIALS, options));
    const rows = Array.isArray(body?.testimonials) ? body.testimonials : [];
    return rows.flatMap((row) => {
      const item = record(row);
      const rating = item?.rating;
      if (!item || !text(item.name) || !text(item.quote)) return [];
      return [{ name: text(item.name), context: text(item.context), quote: text(item.quote), rating: typeof rating === "number" ? rating : null }];
    });
  }

  async pricing(options: ReadOptions = {}): Promise<PublicPricing | null> {
    const body = record(await this.read(PublicLanding.PRICING, options));
    return PublicLanding.isPricing(body) ? body : null;
  }

  /** Enough of the shape to render from: a missing number would otherwise show up as "undefined" on the page. */
  static isPricing(body: Record<string, unknown> | null): body is PublicPricing {
    if (!body || !Array.isArray(body.plans)) return false;
    const plansOk = body.plans.every((plan) => {
      const p = record(plan);
      return !!p && !!text(p.key) && !!text(p.name) && count(p.credits) && count(p.period_days) && count(p.price_paise) && count(p.max_quantity) && maybeCount(p.about_lessons) && maybeCount(p.price_paise_per_credit);
    });
    const oneTime = record(body.one_time);
    const oneTimeOk = body.one_time === null || (!!oneTime && count(oneTime.price_paise_per_credit) && count(oneTime.min_credits) && count(oneTime.valid_days));
    return (
      plansOk && oneTimeOk &&
      [body.signup_credits, body.daily_credits, body.weekly_streak_bonus, body.monthly_streak_bonus, body.bonus_valid_days, body.quick_check_questions].every(count) &&
      maybeCount(body.signup_about_lessons) && maybeCount(body.lesson_credits) && maybeCount(body.retake_credits) &&
      maybeRange(body.sheet_credits) && maybeRange(body.quiz_credits)
    ); // fmt: skip
  }

  private async read(path: string, { clientIp }: ReadOptions): Promise<unknown> {
    try {
      const response = await this.fetcher(`${this.base}${path}`, {
        cache: "no-store",
        signal: AbortSignal.timeout(this.timeoutMs),
        ...(clientIp ? { headers: { "x-forwarded-for": clientIp } } : {}),
      });
      return response.ok ? await response.json() : null;
    } catch {
      return null;
    }
  }
}
