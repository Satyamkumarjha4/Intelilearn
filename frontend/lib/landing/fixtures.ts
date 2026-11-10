import type { PublicPricing } from "@/lib/landing/types";

/** The numbers the server gives at the seeded prices; tests change a field to show the page follows it. */
export function pricing(overrides: Partial<PublicPricing> = {}): PublicPricing {
  return {
    plans: [
      { key: "weekly_pro", name: "Weekly Pro", credits: 100, period_days: 7, price_paise: 4900, max_quantity: 12, price_paise_per_credit: 49, about_lessons: 10 },
      { key: "monthly_pro", name: "Monthly Pro", credits: 500, period_days: 28, price_paise: 19900, max_quantity: 1, price_paise_per_credit: 39.8, about_lessons: 50 },
      { key: "pro_plus", name: "Pro Plus", credits: 750, period_days: 28, price_paise: 27900, max_quantity: 1, price_paise_per_credit: 37.2, about_lessons: 75 },
    ],
    one_time: { price_paise_per_credit: 100, min_credits: 10, max_credits: 5000, valid_days: 365 },
    signup_credits: 30,
    signup_about_lessons: 3,
    daily_credits: 1,
    weekly_streak_bonus: 10,
    monthly_streak_bonus: 10,
    bonus_valid_days: 90,
    lesson_credits: 10,
    retake_credits: 2,
    sheet_credits: { min: 2, max: 3 },
    quiz_credits: { min: 1, max: 4 },
    quick_check_questions: 10,
    ...overrides,
  };
}
