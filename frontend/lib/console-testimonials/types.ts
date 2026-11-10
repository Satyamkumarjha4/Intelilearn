/** The shapes of the console's testimonial endpoints (docs/reference/api.md, "Console"). */

export type ConsoleTestimonial = {
  id: number;
  name: string;
  context: string;
  quote: string;
  rating: number | null;
  position: number;
  is_published: boolean;
  consent_confirmed: boolean;
  is_sample: boolean;
  created_at: string;
  updated_at: string;
};

export type TestimonialList = { testimonials: ConsoleTestimonial[] };

/** What the form holds: text boxes (a rating is "" for none), and the two switches. */
export type TestimonialDraft = { name: string; context: string; quote: string; rating: string; consent_confirmed: boolean; is_published: boolean };

/** What is sent. */
export type TestimonialInput = { name: string; context: string; quote: string; rating: number | null; consent_confirmed: boolean; is_published: boolean };
