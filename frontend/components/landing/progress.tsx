import { ListChecksIcon, RefreshCwIcon, TrendingUpIcon } from "lucide-react";

import { SectionHead } from "@/components/landing/section-head";
import { ProgressExample } from "@/lib/landing/progress-example";
import { cn } from "@/lib/utils";

const LINES = [
  { icon: RefreshCwIcon, text: "Every retake has fresh questions, so you're never just memorising answers." },
  { icon: TrendingUpIcon, text: "See your score against last time and against your best." },
  { icon: ListChecksIcon, text: 'Missed something? "Study this" opens the exact page that teaches it.' },
];

const BAR_LOOK = ["bg-muted", "bg-primary-soft border-2 border-b-0 border-primary/40", "bg-primary"];

/** The retake chart on a teal panel. The panel is the deep teal in light mode and the soft teal in dark mode, so the words
 *  on it keep their contrast in both. The chart is an example and is captioned as one. */
export function Progress() {
  const tries = ProgressExample.TRIES;
  return (
    <section id="progress" className="px-4">
      <div className="mx-auto flex max-w-[1240px] flex-wrap items-center gap-x-14 gap-y-12 rounded-[40px] bg-primary-deep px-6 py-16 text-primary-foreground sm:px-10 sm:py-[88px] dark:bg-primary-soft dark:text-foreground">
        <div className="flex min-w-0 flex-[1_1_400px] flex-col gap-[22px]">
          <SectionHead tone="onPanel" eyebrow="Retakes that show your progress" title="Every attempt makes you better. Now you can see it." />
          <ul className="flex flex-col gap-[18px] text-lg">
            {LINES.map(({ icon: Icon, text }) => (
              <li key={text} className="flex gap-3.5">
                <Icon aria-hidden="true" className="mt-0.5 size-6 shrink-0 text-marigold-soft dark:text-marigold-text" strokeWidth={2.5} />
                <span>{text}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex min-w-0 flex-[1_1_520px] flex-col gap-[22px] rounded-[26px] bg-card p-6 text-card-foreground shadow-[0_24px_48px_oklch(0_0_0/0.2)] sm:p-[34px]">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-heading text-[26px] font-semibold">Your tries</span>
            <span className="rounded-full bg-success-soft px-3.5 py-1.5 text-[15px] font-extrabold text-success-text">Up {ProgressExample.gain} points on last time</span>
          </div>
          <div role="img" aria-label={ProgressExample.label}>
            <div className="flex h-[230px] items-end gap-7 border-b-2 border-border px-2">
              {tries.map((score, index) => (
                <div key={index} className="flex flex-1 flex-col items-center gap-2">
                  <span className="text-[17px] font-extrabold">{score}%</span>
                  <div className={cn("w-full rounded-t-xl", BAR_LOOK[index])} style={{ height: `${score * 2.07}px` }} />
                </div>
              ))}
            </div>
            <div className="mt-2 flex gap-7 px-2 text-[15px] font-bold text-muted-foreground">
              {tries.map((_, index) => (
                <span key={index} className="flex-1 text-center">
                  {ProgressExample.caption(index)}
                </span>
              ))}
            </div>
          </div>
          <div aria-hidden="true" className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-background px-[18px] py-4">
            <div className="flex flex-col">
              <span className="text-[17px] font-extrabold">Radians</span>
              <span className="text-[15px] text-muted-foreground">Taught on Page 2 · Core</span>
            </div>
            <span className="rounded-xl bg-marigold px-[18px] py-3 font-extrabold text-marigold-foreground shadow-[0_4px_0_var(--marigold-deep)]">Study this</span>
          </div>
          <p className="text-center text-sm text-muted-foreground">Example data, to show how progress is displayed</p>
        </div>
      </div>
    </section>
  );
}
