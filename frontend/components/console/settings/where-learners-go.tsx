import type { BandView, Zone } from "@/lib/flow-bands";
import { cn } from "@/lib/utils";

const CELL: Record<Zone, string> = {
  foundations: "bg-marigold-soft text-marigold-text",
  lesson: "bg-primary-soft text-primary-text",
  study: "bg-insight-soft text-insight-text",
};
const SWATCH: Record<Zone, string> = { foundations: "bg-marigold", lesson: "bg-primary", study: "bg-insight" };

/**
 * Where each quick-check score sends a learner, drawn from the settings as they are typed. The colours are the roles
 * of the app: marigold for what is still to learn, teal for the lesson, grape for what the AI says about the learner.
 */
export function WhereLearnersGo({ view, unsaved }: { view: BandView; unsaved: boolean }) {
  const summary = view.legend.map((item) => `${item.range} correct: ${item.text}`).join(". ");
  return (
    <section aria-label="Where learners go" className="rounded-2xl border bg-card shadow-card min-[1000px]:sticky min-[1000px]:top-4">
      <div className="px-[18px] pt-4">
        <h2 className="font-sans text-base font-extrabold">Where learners go</h2>
        <p className="text-[13px] font-semibold text-muted-foreground">{unsaved ? "With your unsaved changes" : "With the current settings"}</p>
      </div>
      <div className="px-[18px] pt-3 pb-4">
        <div role="img" aria-label={summary} className="grid gap-[3px]" style={{ gridTemplateColumns: `repeat(${view.cells.length}, minmax(0, 1fr))` }}>
          {view.cells.map((cell) => (
            <span
              key={cell.score}
              className={cn("grid h-[30px] place-items-center rounded-md font-mono text-[11.5px] font-semibold", CELL[cell.zone])}
            >
              {view.total > 12 && cell.score % 2 === 1 ? "" : cell.score}
            </span>
          ))}
        </div>
        <div className="mt-1 flex justify-between text-[11.5px] font-bold text-muted-foreground" aria-hidden="true">
          <span>0 correct</span>
          <span>{view.total} correct</span>
        </div>
        <ul className="mt-3.5 grid gap-2 text-[12.5px]">
          {view.legend.map((item) => (
            <li key={item.zone} className="flex items-start gap-2">
              <i aria-hidden="true" className={cn("mt-1 size-3 shrink-0 rounded", SWATCH[item.zone])} />
              <span>
                <b>{item.range}</b> {item.text}
              </span>
            </li>
          ))}
        </ul>
        {view.notice ? (
          <p role="status" className="mt-3 rounded-xl bg-marigold-soft px-3 py-2 text-[12.5px] font-bold text-marigold-text">
            {view.notice}
          </p>
        ) : null}
      </div>
    </section>
  );
}
