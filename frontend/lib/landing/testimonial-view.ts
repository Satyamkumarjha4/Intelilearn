import type { PublicTestimonial } from "@/lib/landing/types";

export type Tone = "primary" | "marigold" | "insight";
const TONES: Tone[] = ["primary", "marigold", "insight"];

export type TestimonialCard = {
  name: string;
  context: string;
  quote: string;
  initials: string;
  /** Five flags, one for each star, filled or not; empty when the learner gave no rating (no stars are shown then). */
  stars: boolean[];
  ratingLabel: string | null;
  tone: Tone;
};

/** How a published testimonial is laid out: initials for the round avatar, stars only when there is a rating. */
export class TestimonialView {
  /** The first letters of the first two words of a name, ignoring brackets and punctuation; "?" for nothing readable. */
  static initials(name: string): string {
    const letters = name
      .split(/\s+/)
      .map((word) => word.replace(/[^\p{L}]/gu, ""))
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word.charAt(0).toUpperCase());
    return letters.join("") || "?";
  }

  static stars(rating: number | null): boolean[] {
    if (rating === null || !Number.isInteger(rating) || rating < 1 || rating > 5) return [];
    return [1, 2, 3, 4, 5].map((n) => n <= rating);
  }

  static ratingLabel(rating: number | null): string | null {
    return TestimonialView.stars(rating).length ? `${rating} out of 5 stars` : null;
  }

  static card(testimonial: PublicTestimonial, index: number): TestimonialCard {
    return {
      name: testimonial.name,
      context: testimonial.context,
      quote: testimonial.quote,
      initials: TestimonialView.initials(testimonial.name),
      stars: TestimonialView.stars(testimonial.rating),
      ratingLabel: TestimonialView.ratingLabel(testimonial.rating),
      tone: TONES[index % TONES.length],
    };
  }

  static cards(testimonials: PublicTestimonial[]): TestimonialCard[] {
    return testimonials.map((t, index) => TestimonialView.card(t, index));
  }
}
