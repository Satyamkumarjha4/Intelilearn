import { Markdown } from "@/components/markdown";
import type { RevisionSheet } from "@/lib/types";

const anchor = (index: number) => `subtopic-${index + 1}`;

/** Long-form notes with a table of contents and collapsible sections (all open when printed). */
export function RevisionSheetView({ sheet }: { sheet: RevisionSheet }) {
  return (
    <article className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <h2 className="text-2xl font-semibold tracking-tight">{sheet.title}</h2>
        <Markdown className="text-muted-foreground">{sheet.overview}</Markdown>
      </header>

      <nav aria-label="Contents" className="rounded-lg border p-3 text-sm print:hidden">
        <p className="mb-1 font-medium">Contents</p>
        <ol className="list-decimal pl-5">
          {sheet.subtopics.map((sub, i) => (
            <li key={sub.title}>
              <a className="underline-offset-4 hover:underline" href={`#${anchor(i)}`}>
                {sub.title}
              </a>
            </li>
          ))}
        </ol>
      </nav>

      {sheet.subtopics.map((sub, i) => (
        <details key={sub.title} id={anchor(i)} open className="group rounded-lg border p-4 open:pb-5">
          <summary className="cursor-pointer text-lg font-medium">{sub.title}</summary>
          <div className="mt-3 flex flex-col gap-3">
            <Markdown>{sub.summary}</Markdown>
            <ul className="list-disc pl-5">
              {sub.key_points.map((point) => (
                <li key={point}>
                  <Markdown>{point}</Markdown>
                </li>
              ))}
            </ul>
            {sub.worked_examples.map((example) => (
              <div key={example.problem} className="rounded-lg bg-muted/50 p-3">
                <p className="font-medium">Example</p>
                <Markdown>{example.problem}</Markdown>
                <Markdown className="text-muted-foreground">{example.solution}</Markdown>
              </div>
            ))}
            {sub.common_mistakes.length > 0 && (
              <div>
                <p className="font-medium">Common mistakes</p>
                <ul className="list-disc pl-5 text-muted-foreground">
                  {sub.common_mistakes.map((mistake) => (
                    <li key={mistake}>{mistake}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </details>
      ))}

      {sheet.final_tips.length > 0 && (
        <section>
          <h3 className="mb-1 text-lg font-medium">Final tips</h3>
          <ul className="list-disc pl-5">
            {sheet.final_tips.map((tip) => (
              <li key={tip}>{tip}</li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
