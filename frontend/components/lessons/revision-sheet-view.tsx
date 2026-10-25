import { MistakeList, MutedBox, RememberBox, SheetBox, SheetHeading } from "@/components/lessons/sheet-parts";
import { Markdown } from "@/components/markdown";
import type { RevisionSheet } from "@/lib/types";

const anchor = (index: number) => `subtopic-${index + 1}`;

/** A box per subtopic (summary, key points, worked examples, common mistakes) under a row of links to them, and the
 *  final tips as the closing "Remember". Fixed template: no generated code. */
export function RevisionSheetView({ sheet }: { sheet: RevisionSheet }) {
  return (
    <article className="flex flex-col gap-4">
      <SheetHeading eyebrow="Revision sheet" title={sheet.title}>
        <Markdown>{sheet.overview}</Markdown>
      </SheetHeading>

      <nav aria-label="Contents" className="flex flex-wrap gap-2 print:hidden">
        {sheet.subtopics.map((sub, i) => (
          <a
            key={sub.title}
            href={`#${anchor(i)}`}
            className="rounded-full bg-primary-soft px-3 py-1 text-sm font-bold text-primary-text outline-none hover:bg-primary-soft/70 focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {sub.title}
          </a>
        ))}
      </nav>

      <div className="grid items-start gap-4 md:grid-cols-2">
        {sheet.subtopics.map((sub, i) => (
          <SheetBox key={sub.title} id={anchor(i)} heading={sub.title}>
            <Markdown>{sub.summary}</Markdown>
            {sub.key_points.length > 0 && (
              <ul className="flex list-disc flex-col gap-1.5 pl-5 marker:text-primary">
                {sub.key_points.map((point) => (
                  <li key={point}>
                    <Markdown>{point}</Markdown>
                  </li>
                ))}
              </ul>
            )}
            {sub.worked_examples.map((example) => (
              <MutedBox key={example.problem}>
                <p className="text-sm font-extrabold">Example</p>
                <Markdown>{example.problem}</Markdown>
                <Markdown className="text-muted-foreground [&_.katex-display]:overflow-x-auto">{example.solution}</Markdown>
              </MutedBox>
            ))}
            {sub.common_mistakes.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <p className="text-sm font-extrabold">Common mistakes</p>
                <MistakeList items={sub.common_mistakes} />
              </div>
            )}
          </SheetBox>
        ))}
        {sheet.final_tips.length > 0 && (
          <RememberBox>
            <ul className="flex list-disc flex-col gap-1 pl-5 marker:text-insight">
              {sheet.final_tips.map((tip) => (
                <li key={tip}>{tip}</li>
              ))}
            </ul>
          </RememberBox>
        )}
      </div>
    </article>
  );
}
