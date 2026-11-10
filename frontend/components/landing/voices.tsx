import { Stars } from "@/components/landing/stars";
import { SectionHead } from "@/components/landing/section-head";
import { TestimonialView, type TestimonialCard } from "@/lib/landing/testimonial-view";
import type { PublicTestimonial } from "@/lib/landing/types";
import { cn } from "@/lib/utils";

const TONES = {
  primary: "bg-primary-soft text-primary-text",
  marigold: "bg-marigold-soft text-marigold-text",
  insight: "bg-insight-soft text-insight-text",
} as const;

/**
 * "What learners say": only the testimonials the console has published with the learner's consent. When there are none
 * the section is the maker's note instead, never a made-up quote. A server component, so it is whole without script.
 */
export function Voices({ testimonials }: { testimonials: PublicTestimonial[] }) {
  const cards = TestimonialView.cards(testimonials);
  return (
    <section id="voices" aria-label={cards.length ? "What learners say" : "Why Socra exists"} className="mx-auto w-full max-w-[1200px] px-4 pt-20 sm:px-6 sm:pt-[104px]">
      {cards.length ? <Quotes cards={cards} /> : <MakerNote />}
    </section>
  );
}

function Quotes({ cards }: { cards: TestimonialCard[] }) {
  return (
    <div className="flex flex-col gap-8">
      <SectionHead eyebrow="From learners" title="What learners say" />
      <ul className="flex flex-wrap gap-6">
        {cards.map((card, index) => (
          <li key={index} className="flex min-w-0 flex-[1_1_320px]">
            <figure className="flex w-full flex-col gap-4 rounded-[22px] border border-border bg-card p-7 shadow-card">
              {card.stars.length ? (
                <div role="img" aria-label={card.ratingLabel ?? undefined} className="flex min-h-6">
                  <Stars filled={card.stars} />
                </div>
              ) : null}
              <blockquote className="text-[19px] leading-normal">“{card.quote}”</blockquote>
              <figcaption className="mt-auto flex items-center gap-3">
                <span aria-hidden="true" className={cn("flex size-11 shrink-0 items-center justify-center rounded-full font-extrabold", TONES[card.tone])}>
                  {card.initials}
                </span>
                <span className="flex min-w-0 flex-col">
                  <strong>{card.name}</strong>
                  <span className="text-[15px] text-muted-foreground">{card.context}</span>
                </span>
              </figcaption>
            </figure>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Draft words from the mockup, with an "S" until a photo is sent. */
function MakerNote() {
  return (
    <div className="flex flex-wrap items-center gap-9 rounded-[26px] border border-border bg-card p-6 shadow-card sm:p-9">
      <span aria-hidden="true" className="flex size-[140px] shrink-0 items-center justify-center rounded-full bg-primary-soft font-heading text-6xl font-semibold text-primary-text">
        S
      </span>
      <div className="flex min-w-0 flex-[1_1_380px] flex-col gap-3">
        <span className="text-base font-extrabold text-primary-text">Why Socra exists</span>
        <blockquote className="font-heading text-[clamp(21px,2.4vw,26px)] leading-snug font-medium">
          “Most lessons start from zero. I kept spending evenings on things I already knew, so I built a tutor that checks first and teaches only what&apos;s missing.”
        </blockquote>
        <p className="font-extrabold">
          Satyam <span className="font-semibold text-muted-foreground">· maker of Socra, computer science student</span>
        </p>
      </div>
    </div>
  );
}
