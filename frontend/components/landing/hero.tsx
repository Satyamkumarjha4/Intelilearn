import Link from "next/link";

import { HeroDemoCard } from "@/components/landing/hero-demo";
import { buttonVariants } from "@/components/ui/button";
import { LANGUAGES, REGISTER_HREF } from "@/lib/landing-content";
import type { DemoQuestion } from "@/lib/types";

/** The first screen: the promise, the two ways on, and a question to try right here (chosen by the page). */
export function Hero({ question }: { question: DemoQuestion }) {
  return (
    <section className="mx-auto grid w-full max-w-[1180px] grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)] items-center gap-14 px-4 pt-11 pb-16 max-[900px]:grid-cols-1 max-[900px]:gap-9">
      <div>
        <span className="inline-block rounded-full bg-insight-soft px-3.5 py-1.5 text-[13px] font-extrabold text-insight-text">Teaching that starts with a question</span>
        <h1 className="mt-[18px] text-[clamp(38px,5.2vw,62px)] leading-[1.04] tracking-[-0.01em]">
          Learn only what you{" "}
          <span className="bg-[linear-gradient(transparent_60%,var(--marigold)_60%,var(--marigold)_90%,transparent_90%)] px-1 [box-decoration-break:clone]">don&apos;t know yet.</span>
        </h1>
        <p className="mt-[18px] max-w-[52ch] text-lg text-muted-foreground">
          Like Socrates, Socra asks before it teaches. Pick any topic, answer a quick 10-question check, and get an interactive lesson that starts exactly where you are.
        </p>
        <div className="mt-7 flex flex-wrap gap-3">
          <Link href={REGISTER_HREF} className={buttonVariants({ size: "xl" })}>
            Get started
          </Link>
          <Link href="#how" className={buttonVariants({ variant: "outline", size: "xl" })}>
            See how it works
          </Link>
        </div>
        <p className="mt-[18px] text-sm font-bold text-muted-foreground">
          For school, college and beyond · Lessons in{" "}
          {LANGUAGES.map(({ label, lang }, n) => (
            <span key={lang}>
              {n > 0 && (n === LANGUAGES.length - 1 ? " and " : ", ")}
              <span lang={lang}>{label}</span>
            </span>
          ))}
        </p>
      </div>
      <HeroDemoCard initial={question} />
    </section>
  );
}
