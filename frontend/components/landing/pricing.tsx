import { CalendarCheckIcon, ReceiptTextIcon, ShieldCheckIcon, Undo2Icon } from "lucide-react";
import Link from "next/link";

import { SectionHead } from "@/components/landing/section-head";
import { buttonVariants } from "@/components/ui/button";
import { REGISTER_HREF } from "@/lib/landing-content";
import { PricingWords, type PlanCard } from "@/lib/landing/pricing-words";
import type { PublicPricing } from "@/lib/landing/types";
import { cn } from "@/lib/utils";

const POLICY = [
  { icon: Undo2Icon, bold: "Credits back", text: " if anything fails to build" },
  { icon: CalendarCheckIcon, bold: "Prepaid.", text: " Nothing renews automatically" },
  { icon: ShieldCheckIcon, bold: "Secure checkout.", text: " Payment details stay with the provider" },
  { icon: ReceiptTextIcon, bold: "Prices include tax", text: "" },
];

/** The plans, the top-up, what credits buy and the four promises. Every number is read from the pricing endpoint; if it
 *  could not be read there is no number on the section at all, only a plain line saying so. */
export function Pricing({ pricing, signedIn }: { pricing: PublicPricing | null; signedIn: boolean }) {
  const cards = pricing ? PricingWords.cards(pricing, signedIn, REGISTER_HREF) : [];
  const topUp = pricing ? PricingWords.topUp(pricing) : null;
  const rows = pricing ? PricingWords.costRows(pricing) : [];
  return (
    <section id="pricing" className="border-y border-border bg-card">
      <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-10 px-4 py-20 sm:px-6 sm:py-[104px]">
        <SectionHead eyebrow="Pricing" title="Start free. Pay only for what you learn." text="Every plan includes every feature. Plans only change how many credits you get." />

        {pricing ? (
          <ul className="grid grid-cols-2 gap-6 max-[680px]:grid-cols-1">
            {cards.map((card) => (
              <PlanCardView key={card.key} card={card} />
            ))}
          </ul>
        ) : (
          <p role="status" className="rounded-[22px] border-2 border-dashed border-border px-6 py-8 text-lg text-muted-foreground">
            Prices are not available right now. Please try again in a little while.
          </p>
        )}

        {topUp ? (
          <div className="flex flex-wrap items-center justify-between gap-4 rounded-[18px] border-2 border-dashed border-border px-6 py-[18px]">
            <span className="text-[17px]">
              <strong>{topUp.bold}</strong>
              {topUp.text}
            </span>
            <Link href={signedIn ? "/buy" : REGISTER_HREF} className={buttonVariants({ variant: "link", size: "lg", className: "text-base" })}>
              Top up
            </Link>
          </div>
        ) : null}

        {rows.length ? (
          <div className="flex flex-col gap-3.5 rounded-[22px] border-2 border-marigold-deep/40 bg-marigold-soft px-6 py-6 sm:px-[30px]">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="font-heading text-xl font-semibold">What credits buy</h3>
              <span className="text-[15px] text-muted-foreground">Every button shows its cost before you click</span>
            </div>
            <dl className="flex flex-wrap gap-3">
              {rows.map((row) => (
                <div key={row.label} className="flex min-w-0 flex-[1_1_200px] justify-between gap-3 rounded-[14px] bg-card px-4 py-3 text-base">
                  <dt>{row.label}</dt>
                  <dd className="font-extrabold">{row.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        ) : null}

        <ul className="flex flex-wrap gap-4">
          {POLICY.map(({ icon: Icon, bold, text }) => (
            <li key={bold} className="flex min-w-0 flex-[1_1_240px] items-start gap-3 text-base">
              <Icon aria-hidden="true" className="size-6 shrink-0 text-primary-text" strokeWidth={2.4} />
              <span>
                <strong>{bold}</strong>
                {text}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function PlanCardView({ card }: { card: PlanCard }) {
  return (
    <li className="flex min-w-0">
      <article
        aria-labelledby={`plan-${card.key}`}
        className={cn(
          "relative flex w-full flex-col gap-3 rounded-[22px] p-[30px]",
          card.featured ? "border-[3px] border-primary bg-primary-soft shadow-[0_20px_44px_oklch(0.64_0.12_190/0.2)]" : "border-2 border-border bg-background",
        )}
      >
        {card.badge ? <span className="absolute -top-3.5 left-6 rounded-full bg-marigold px-3.5 py-1 text-sm font-extrabold text-marigold-foreground">{card.badge}</span> : null}
        <h3 id={`plan-${card.key}`} className="font-sans text-xl font-extrabold">
          {card.name}
        </h3>
        <p>
          <span className="font-heading text-[44px] leading-none font-semibold">{card.price}</span>
          {card.per ? <span className="font-bold text-muted-foreground"> {card.per}</span> : null}
        </p>
        {card.tagline ? <p className="text-base text-muted-foreground">{card.tagline}</p> : null}
        <ul className="flex flex-col gap-1.5 text-base">
          {card.lines.map((line, index) => (
            <li key={index}>
              {line.bold ? <strong>{line.bold}</strong> : null}
              {line.text}
            </li>
          ))}
        </ul>
        <Link href={card.cta.href} className={buttonVariants({ variant: card.featured ? "default" : "outline", size: "xl", className: "mt-auto" })}>
          {card.cta.label}
        </Link>
      </article>
    </li>
  );
}
