"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { CTA, REGISTER_HREF } from "@/lib/landing-content";
import { PendingTopic } from "@/lib/pending-topic";
import { PricingWords } from "@/lib/landing/pricing-words";
import type { PublicPricing } from "@/lib/landing/types";

/** The last push, on marigold: name a topic and go sign up. The topic waits in `sessionStorage` for the screens after
 *  sign-up. It promises free lessons only when the pricing endpoint says there are free credits. */
export function CtaBand({ pricing }: { pricing: PublicPricing | null }) {
  const router = useRouter();
  const [topic, setTopic] = useState("");
  const promise = PricingWords.hasFreeCredits(pricing);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    new PendingTopic(undefined, CTA.maxLength).save(topic);
    router.push(REGISTER_HREF);
  };

  return (
    <section id="start" aria-labelledby="cta-title" className="mx-auto mb-20 w-full max-w-[1200px] px-4 sm:mb-[104px] sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-6 rounded-[28px] bg-marigold px-6 py-12 text-marigold-foreground shadow-[0_10px_0_var(--marigold-deep)] sm:px-11 sm:py-[60px]">
        <div className="flex min-w-0 flex-[1_1_380px] flex-col gap-2">
          <h2 id="cta-title" className="text-[clamp(28px,4vw,46px)] leading-[1.1] font-semibold">
            {promise ? CTA.title : CTA.fallbackTitle}
          </h2>
          <p className="text-[19px] font-bold">{CTA.text}</p>
        </div>
        <form onSubmit={submit} className="flex min-w-0 flex-[1_1_420px] gap-2 rounded-[18px] bg-card p-1.5 max-[560px]:flex-col">
          <input
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            maxLength={CTA.maxLength}
            placeholder={CTA.placeholder}
            aria-label="Topic"
            className="min-w-0 flex-1 rounded-xl bg-transparent px-3.5 py-2.5 text-[17px] text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
          />
          <Button type="submit" size="xl">
            {PricingWords.startLabel(pricing)}
          </Button>
        </form>
      </div>
    </section>
  );
}
