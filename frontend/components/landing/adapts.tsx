import { ArrowUpIcon, FileTextIcon, LayersIcon } from "lucide-react";

import { SectionHead } from "@/components/landing/section-head";
import { Stars } from "@/components/landing/stars";
import { SAMPLE_LEVELS, SAMPLE_TOPIC } from "@/lib/landing/sample-quiz-content";
import { cn } from "@/lib/utils";

const LINES = [
  { icon: ArrowUpIcon, tone: "bg-marigold-soft text-marigold-text", lead: "Aced the Test?", text: " Socra offers an Advanced lesson to go further." },
  { icon: LayersIcon, tone: "bg-primary-soft text-primary-text", lead: "Found it tough?", text: " Socra offers a Foundations lesson to build up the basics." },
  { icon: FileTextIcon, tone: "bg-insight-soft text-insight-text", lead: "Perfect Quick check?", text: " Choose an Expert lesson, or just the cheat sheet and revision sheet for fewer credits." },
];

/** "Adapts to your level": what the lesson does at each level, and the star rating that skips the quiz. */
export function Adapts() {
  return (
    <section id="features" className="mx-auto flex w-full max-w-[1200px] flex-wrap items-center gap-x-14 gap-y-12 px-4 py-20 sm:px-6 sm:py-[104px]">
      <div className="flex min-w-0 flex-[1_1_400px] flex-col gap-[22px]">
        <SectionHead eyebrow="Adapts to your level" title="Already know the basics? Skip them." />
        <p className="text-[19px] text-muted-foreground">New to it? Your lesson starts with the basics you need first. Already strong? It skips ahead to the deep end.</p>
        <ul className="mt-1.5 flex flex-col gap-4">
          {LINES.map(({ icon: Icon, tone, lead, text }) => (
            <li key={lead} className="flex items-start gap-3.5">
              <span aria-hidden="true" className={cn("flex size-9 shrink-0 items-center justify-center rounded-[10px]", tone)}>
                <Icon className="size-5" strokeWidth={2.5} />
              </span>
              <span>
                <strong>{lead}</strong>
                {text}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex min-w-0 flex-[1_1_520px] flex-col gap-5 rounded-[26px] border-2 border-border bg-card p-6 shadow-card sm:p-[34px]">
        <p className="text-[15px] font-extrabold text-muted-foreground">Rather skip the quiz? Rate yourself.</p>
        <p className="text-[22px] font-extrabold">How well do you know {SAMPLE_TOPIC}?</p>
        <div role="img" aria-label="3.5 out of 5 stars">
          <Stars filled={[true, true, true, "half", false]} size={44} className="flex gap-1.5 max-[420px]:[&_svg]:size-9" />
        </div>
        <p className="rounded-[14px] bg-marigold-soft px-[18px] py-3.5 text-lg font-bold">“I can solve most simple problems and I am starting on harder ones.”</p>
        <table className="w-full overflow-hidden rounded-2xl text-left text-base">
          <caption className="sr-only">The level each score gives, and the three pages of the lesson for it</caption>
          <thead>
            <tr className="bg-background text-sm font-extrabold text-muted-foreground">
              <th scope="col" className="px-4 py-3">Your level</th>
              <th scope="col" className="px-4 py-3">Your three pages</th>
            </tr>
          </thead>
          <tbody>
            {SAMPLE_LEVELS.map((level, index) => (
              <tr key={level.name} className={cn("border-t border-border", index === 1 && "bg-primary-soft")}>
                <th scope="row" className="w-[34%] px-4 py-3 align-top font-extrabold">{level.name}</th>
                <td className="px-4 py-3">{level.pages.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
