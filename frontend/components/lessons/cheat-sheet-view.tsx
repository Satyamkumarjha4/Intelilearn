import { MutedBox, RememberBox, SheetBox, SheetHeading } from "@/components/lessons/sheet-parts";
import { Markdown } from "@/components/markdown";
import { CheatGroups } from "@/lib/cheat-groups";
import type { CheatItem, CheatSheet } from "@/lib/types";

function Formula({ item }: { item: CheatItem }) {
  return (
    <MutedBox>
      <p className="text-sm font-extrabold">{item.label}</p>
      {item.formula && <Markdown className="overflow-x-auto text-base [&_.katex-display]:my-1">{`$$${item.formula}$$`}</Markdown>}
      {item.content && <Markdown className="text-sm">{item.content}</Markdown>}
      {item.variables.length > 0 && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 text-sm text-muted-foreground">
          {item.variables.map((v) => (
            <div key={v.symbol} className="contents">
              <dt>
                <Markdown>{`$${v.symbol}$`}</Markdown>
              </dt>
              <dd>{v.meaning}</dd>
            </div>
          ))}
        </dl>
      )}
      {item.when_to_use && <p className="text-sm text-muted-foreground">Use when: {item.when_to_use}</p>}
    </MutedBox>
  );
}

/** A grid of boxes, one per section: formulas in a muted box, key terms as a definition list, and the rest as points.
 *  The sheet's summary is the closing "Remember". Fixed template: no generated code. */
export function CheatSheetView({ sheet }: { sheet: CheatSheet }) {
  return (
    <article className="flex flex-col gap-4">
      <SheetHeading eyebrow="Cheat sheet" title={sheet.title} />
      <div className="grid items-start gap-4 sm:grid-cols-2">
        {sheet.sections.map((section) => {
          const { formulas, terms, points } = CheatGroups.of(section.items);
          return (
            <SheetBox key={section.heading} heading={section.heading}>
              {formulas.map((item) => (
                <Formula key={item.label} item={item} />
              ))}
              {terms.length > 0 && (
                <dl className="flex flex-col gap-2">
                  {terms.map((item) => (
                    <div key={item.label}>
                      <dt className="font-extrabold">{item.label}</dt>
                      <dd className="text-muted-foreground">
                        <Markdown>{item.content}</Markdown>
                        {item.when_to_use && <p className="mt-0.5 text-sm">Use when: {item.when_to_use}</p>}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
              {points.length > 0 && (
                <ul className="flex flex-col gap-2">
                  {points.map((item) => (
                    <li key={item.label} className="flex flex-col">
                      <span className="font-extrabold">{item.label}</span>
                      <Markdown className="text-muted-foreground">{item.content}</Markdown>
                      {item.when_to_use && <p className="text-sm text-muted-foreground">Use when: {item.when_to_use}</p>}
                    </li>
                  ))}
                </ul>
              )}
            </SheetBox>
          );
        })}
        {sheet.summary && (
          <RememberBox>
            <Markdown>{sheet.summary}</Markdown>
          </RememberBox>
        )}
      </div>
    </article>
  );
}
