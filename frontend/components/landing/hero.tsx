import Link from "next/link";

import { SampleQuickCheck } from "@/components/landing/sample-quick-check";
import { buttonVariants } from "@/components/ui/button";
import { HERO, REGISTER_HREF } from "@/lib/landing-content";
import { PricingWords } from "@/lib/landing/pricing-words";
import type { PublicPricing } from "@/lib/landing/types";

/** The first screen: the promise, the two ways on, and a sample Quick check to try right here (no sign-up, no network). */
export function Hero({ pricing }: { pricing: PublicPricing | null }) {
  return (
    <section id="top" className="mx-auto flex w-full max-w-[1240px] flex-wrap items-center gap-x-14 gap-y-12 px-4 pt-14 pb-20 sm:px-6 sm:pt-[72px] sm:pb-24">
      <div className="flex min-w-0 flex-[1_1_480px] flex-col gap-6">
        <span className="self-start rounded-full bg-marigold-soft px-4 py-1.5 text-[15px] font-extrabold text-marigold-text">{HERO.badge}</span>
        <h1 className="text-[clamp(34px,5vw,56px)] leading-[1.04] font-semibold tracking-[-0.01em]">{HERO.title}</h1>
        <p className="max-w-[540px] text-[clamp(18px,2vw,21px)] text-muted-foreground">{HERO.text}</p>
        <div className="flex flex-wrap items-center gap-4">
          <Link href={REGISTER_HREF} className={buttonVariants({ size: "xl", className: "h-14 px-7 text-[18px]" })}>
            {PricingWords.startLabel(pricing)}
          </Link>
          <Link href="#how" className={buttonVariants({ variant: "outline", size: "xl", className: "h-14 px-5 text-[17px]" })}>
            See how it works
          </Link>
        </div>
        <p className="text-[15px] text-muted-foreground">{HERO.note}</p>
      </div>
      <SampleQuickCheck />
    </section>
  );
}
