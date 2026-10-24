import { Markdown } from "@/components/markdown";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CheatSheet } from "@/lib/types";

/** A dense grid of formula and rule cards. Fixed template: no generated code. */
export function CheatSheetView({ sheet }: { sheet: CheatSheet }) {
  return (
    <article className="flex flex-col gap-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">{sheet.title}</h2>
        <Markdown className="text-muted-foreground">{sheet.summary}</Markdown>
      </header>
      {sheet.sections.map((section) => (
        <section key={section.heading} className="flex flex-col gap-3">
          <h3 className="text-lg font-medium">{section.heading}</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            {section.items.map((item) => (
              <Card key={item.label} size="sm" className="break-inside-avoid">
                <CardHeader>
                  <CardTitle className="flex items-center justify-between gap-2">
                    <span>{item.label}</span>
                    <Badge variant="outline">{item.kind}</Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-2">
                  <Markdown>{item.content}</Markdown>
                  {item.formula && <Markdown className="overflow-x-auto text-base">{`$$${item.formula}$$`}</Markdown>}
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
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      ))}
    </article>
  );
}
