import { SectionHead } from "@/components/landing/section-head";

const LINES = [
  { lead: "Cheat sheet:", text: "everything important on one page: key terms, formulas and rules." },
  { lead: "Revision sheet:", text: "key points, quick self-checks and common mistakes." },
  { lead: "Quick quizzes:", text: "practise any topic, or your own lessons." },
];

/** "Revise what you learn": what the study sheets and quick quizzes are, with two tilted sheets as the picture. */
export function Revise() {
  return (
    <section className="mx-auto flex w-full max-w-[1200px] flex-wrap items-center gap-x-14 gap-y-12 px-4 py-20 sm:px-6 sm:py-[104px]">
      <div className="flex min-w-0 flex-[1_1_380px] flex-col gap-5">
        <SectionHead eyebrow="Revise what you learn" title="Everything you need to make it stick." />
        <p className="text-[19px] text-muted-foreground">Turn any lesson, or any topic, into a one-page sheet for the night before.</p>
        <ul className="flex flex-col gap-3.5 text-lg">
          {LINES.map(({ lead, text }) => (
            <li key={lead}>
              <strong>{lead}</strong> <span className="text-muted-foreground">{text}</span>
            </li>
          ))}
        </ul>
      </div>
      <div aria-hidden="true" className="min-w-0 flex-[1_1_520px] px-2 pt-2 pb-6">
        <div className="lift flex w-[82%] -rotate-2 flex-col gap-4 rounded-[22px] border border-border bg-card p-7 shadow-card max-[480px]:w-[92%]">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-heading text-[22px] font-semibold">Cheat sheet · Trigonometry</span>
            <span className="rounded-full bg-primary-soft px-3 py-1 text-sm font-extrabold text-primary-text">1 page</span>
          </div>
          <div className="flex flex-wrap gap-3">
            <div className="min-w-[140px] flex-[1_1_140px] rounded-[14px] bg-background p-3.5 text-base">
              <div className="mb-1 font-extrabold">Formulas</div>sin = O/H, cos = A/H, tan = O/A
            </div>
            <div className="min-w-[140px] flex-[1_1_140px] rounded-[14px] bg-background p-3.5 text-base">
              <div className="mb-1 font-extrabold">Rule</div>sin²θ + cos²θ = 1
            </div>
          </div>
        </div>
        <div className="lift relative -mt-9 ml-[18%] flex w-[82%] rotate-[1.5deg] flex-col gap-3.5 rounded-[22px] border border-border bg-card p-7 shadow-[0_20px_48px_oklch(0.26_0.025_190/0.14)] max-[480px]:ml-[8%] max-[480px]:w-[92%] dark:shadow-[0_20px_48px_oklch(0_0_0/0.4)]">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-heading text-[22px] font-semibold">Revision sheet · Trigonometry</span>
            <span className="rounded-full bg-insight-soft px-3 py-1 text-sm font-extrabold text-insight-text">Self-check</span>
          </div>
          <div className="flex items-center gap-3 text-base">
            <span className="size-5 shrink-0 rounded-[5px] border-2 border-insight" />
            When is tan θ undefined?
          </div>
          <div className="rounded-[14px] bg-marigold-soft px-3.5 py-3 text-base">
            <strong>Common mistake:</strong> leaving the calculator in degrees when the question uses radians.
          </div>
        </div>
      </div>
    </section>
  );
}
