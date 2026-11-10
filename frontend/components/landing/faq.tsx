import { ChevronDownIcon } from "lucide-react";
import Link from "next/link";

import { FaqContent } from "@/lib/landing/faq-content";
import type { PublicPricing } from "@/lib/landing/types";

/** The questions, as a plain disclosure for each (details and summary: keyboard and screen reader work without script). */
export function Faq({ pricing }: { pricing: PublicPricing | null }) {
  return (
    <section id="faq" className="mx-auto flex w-full max-w-[880px] flex-col gap-7 px-4 py-20 sm:px-6 sm:py-[104px]">
      <h2 className="text-[clamp(30px,4vw,44px)] font-semibold">Questions</h2>
      <div className="flex flex-col gap-3">
        {FaqContent.items(pricing).map((item, index) => (
          <details key={item.question} open={index === 0} className="group rounded-[18px] border-2 border-border bg-card px-6 py-5 open:border-primary/40">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-4 rounded-md text-[19px] font-extrabold outline-none focus-visible:ring-3 focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
              {item.question}
              <ChevronDownIcon aria-hidden="true" className="size-5 shrink-0 text-muted-foreground motion-safe:transition-transform group-open:rotate-180" />
            </summary>
            <p className="mt-3 text-muted-foreground">
              {item.answer.map((part, i) =>
                typeof part === "string" ? (
                  part
                ) : (
                  <Link key={i} href={part.href} className="font-bold text-primary-text underline underline-offset-4 outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
                    {part.text}
                  </Link>
                ),
              )}
            </p>
          </details>
        ))}
      </div>
    </section>
  );
}
