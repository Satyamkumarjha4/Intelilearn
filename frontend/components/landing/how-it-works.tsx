import { CheckIcon } from "lucide-react";

import { SectionHead } from "@/components/landing/section-head";
import { cn } from "@/lib/utils";

type Props = { quickCheckQuestions: number | null };

const Chip = ({ n, tone }: { n: number; tone: "primary" | "marigold" | "insight" }) => (
  <span aria-hidden="true" className={cn("flex size-11 items-center justify-center rounded-[13px] font-heading text-[22px] font-semibold", tone === "primary" && "bg-primary text-primary-foreground", tone === "marigold" && "bg-marigold text-marigold-foreground", tone === "insight" && "bg-insight text-primary-foreground")}>
    {n}
  </span>
);

function Step({ n, tone, label, title, text, children }: { n: number; tone: "primary" | "marigold" | "insight"; label: string; title: string; text: string; children: React.ReactNode }) {
  return (
    <li className="lift flex min-w-0 flex-[1_1_320px] flex-col gap-4 rounded-[22px] border-2 border-border bg-background p-7">
      <div className="flex items-center gap-3">
        <Chip n={n} tone={tone} />
        <span className="text-[15px] font-extrabold text-muted-foreground">{label}</span>
      </div>
      <h3 className="text-[26px] leading-tight font-semibold">{title}</h3>
      <p className="text-lg text-muted-foreground">{text}</p>
      <div aria-hidden="true" className="mt-auto flex flex-col gap-2.5 rounded-2xl border border-border bg-card p-[18px]">
        {children}
      </div>
    </li>
  );
}

/** The three steps, each with a small picture of the screen it describes (illustrations, so hidden from a screen reader). */
export function HowItWorks({ quickCheckQuestions }: Props) {
  const quiz = quickCheckQuestions ? `Answer ${quickCheckQuestions} quick questions` : "Answer a few quick questions";
  return (
    <section id="how" className="border-y border-border bg-card">
      <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-11 px-4 py-20 sm:px-6 sm:py-24">
        <SectionHead eyebrow="How it works" title="Three steps, and no time spent on what you already know." />
        <ol className="flex flex-wrap gap-7">
          <Step n={1} tone="primary" label="Quick check or star rating" title="Discover what you already know" text={`${quiz}, or rate yourself from half a star to five if you'd rather skip the quiz.`}>
            <div className="flex justify-between text-sm font-extrabold text-muted-foreground">
              <span>Quick check</span>
              {quickCheckQuestions ? <span>2 of {quickCheckQuestions}</span> : null}
            </div>
            <div className="text-[17px] font-extrabold">Which ratio is opposite over hypotenuse?</div>
            <div className="rounded-xl border-2 border-primary bg-primary-soft px-3.5 py-2.5 text-base font-extrabold text-primary-text">Sine</div>
            <div className="rounded-xl border-2 border-border px-3.5 py-2.5 text-base font-bold">Cosine</div>
            <div className="rounded-xl border-2 border-border px-3.5 py-2.5 text-base font-bold">I don&apos;t know yet</div>
          </Step>
          <Step n={2} tone="marigold" label="Your 3-page lesson" title="Learn exactly what you're missing" text="Three pages written for your level, like a notebook you can come back to any time.">
            <div className="text-sm font-extrabold text-muted-foreground">Building your lesson</div>
            {["Page 1 · Introduction", "Page 2 · Core"].map((page) => (
              <div key={page} className="flex items-center gap-2.5 text-base font-bold">
                <span className="flex size-6 items-center justify-center rounded-full bg-primary text-primary-foreground">
                  <CheckIcon className="size-3.5" strokeWidth={3.5} />
                </span>
                {page}
              </div>
            ))}
            <div className="flex items-center gap-2.5 text-base font-bold text-muted-foreground">
              <span className="size-6 rounded-full border-[3px] border-marigold" />
              Page 3 · Going further
            </div>
            <div className="h-3 overflow-hidden rounded-md bg-muted">
              <div className="h-3 w-[70%] bg-marigold" />
            </div>
          </Step>
          <Step n={3} tone="insight" label="The Test" title="See how much you've improved" text="Questions marked the moment you hand in, with a clear list of what to look at again.">
            <div className="flex items-baseline gap-2.5">
              <span className="font-heading text-[44px] leading-none font-semibold text-primary-text">80%</span>
              <span className="text-base font-bold text-muted-foreground">16 of 20 marks</span>
            </div>
            <div className="text-sm font-extrabold text-muted-foreground">Worth another look</div>
            {["The sine rule", "Radians"].map((topic) => (
              <div key={topic} className="flex items-center justify-between border-t border-border pt-2.5 text-base font-bold">
                <span>{topic}</span>
                <span className="font-extrabold text-primary-text">Study this</span>
              </div>
            ))}
          </Step>
        </ol>
        <p className="text-sm text-muted-foreground">Example screens, to show what each step looks like.</p>
      </div>
    </section>
  );
}
