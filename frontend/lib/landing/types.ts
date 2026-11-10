/** The shapes of the two public endpoints the landing page reads (docs/reference/api.md, "Public"). */

export type PublicTestimonial = { name: string; context: string; quote: string; rating: number | null };

export type PublicPlan = {
  key: string;
  name: string;
  credits: number;
  period_days: number;
  price_paise: number;
  max_quantity: number;
  price_paise_per_credit: number | null;
  about_lessons: number | null;
};

export type CostRange = { min: number; max: number };

export type PublicPricing = {
  plans: PublicPlan[];
  one_time: { price_paise_per_credit: number; min_credits: number; max_credits: number; valid_days: number } | null;
  signup_credits: number;
  signup_about_lessons: number | null;
  daily_credits: number;
  weekly_streak_bonus: number;
  monthly_streak_bonus: number;
  bonus_valid_days: number;
  lesson_credits: number | null;
  retake_credits: number | null;
  sheet_credits: CostRange | null;
  quiz_credits: CostRange | null;
  quick_check_questions: number;
};
