import { LandingFooter } from "@/components/landing/landing-footer";
import { LandingHeader } from "@/components/landing/landing-header";
import { Markdown } from "@/components/markdown";
import type { Block, ParsedLegal } from "@/lib/legal-document";

/** The public header and footer of the landing page around a page of words. */
export function LegalShell({ children }: { children: React.ReactNode }) {
  return (
    <>
      <LandingHeader onLanding={false} />
      <main className="flex flex-1 flex-col">{children}</main>
      <LandingFooter />
    </>
  );
}

/** Legal copy as a readable page: about 70 characters a line, a "last updated" line under the title, and a table of
 *  contents (beside the text on a wide screen, folded at the top on a narrow one). Nothing here is written by the page:
 *  the words come from `content/legal`. */
export function LegalPage({ title, doc }: { title: string; doc: ParsedLegal }) {
  const toc = doc.sections.map((section) => ({ id: section.id, label: `${section.number ? `${section.number}. ` : ""}${section.title}` }));
  return (
    <LegalShell>
      <div className="mx-auto grid w-full max-w-5xl gap-10 px-4 py-10 lg:grid-cols-[minmax(0,70ch)_15rem] lg:justify-between">
        <article className="flex min-w-0 flex-col gap-6">
          <header className="flex flex-col gap-2">
            <h1 className="font-heading text-4xl font-semibold tracking-tight">{title}</h1>
            {doc.updated && <p className="text-sm text-muted-foreground">Last updated: {doc.updated}</p>}
          </header>

          <details className="rounded-xl border-[1.5px] border-border bg-card px-4 py-3 lg:hidden">
            <summary className="cursor-pointer font-extrabold outline-none focus-visible:ring-3 focus-visible:ring-ring/50">On this page</summary>
            <TocList toc={toc} className="mt-3" />
          </details>

          <Blocks blocks={doc.intro} />
          {doc.sections.map((section) => (
            <section key={section.id} id={section.id} aria-labelledby={`${section.id}-title`} className="flex scroll-mt-6 flex-col gap-3">
              <h2 id={`${section.id}-title`} className="font-heading text-2xl font-semibold tracking-tight">
                {section.number ? `${section.number}. ` : ""}
                {section.title}
              </h2>
              <Blocks blocks={section.blocks} />
            </section>
          ))}
        </article>

        <aside className="max-lg:hidden" aria-label="On this page">
          <nav className="sticky top-6 flex flex-col gap-2">
            <p className="font-mono text-xs font-bold tracking-wider text-muted-foreground uppercase">On this page</p>
            <TocList toc={toc} />
          </nav>
        </aside>
      </div>
    </LegalShell>
  );
}

function TocList({ toc, className }: { toc: { id: string; label: string }[]; className?: string }) {
  return (
    <ol className={`flex flex-col gap-1 text-sm ${className ?? ""}`}>
      {toc.map((item) => (
        <li key={item.id}>
          <a href={`#${item.id}`} className="block rounded-md py-0.5 font-semibold text-muted-foreground underline-offset-4 outline-none hover:text-foreground hover:underline focus-visible:ring-3 focus-visible:ring-ring/50">
            {item.label}
          </a>
        </li>
      ))}
    </ol>
  );
}

function Blocks({ blocks }: { blocks: Block[] }) {
  return blocks.map((block, index) =>
    block.kind === "text" ? (
      <Markdown key={index} className="gap-3 text-base leading-relaxed [&_a]:font-bold [&_a]:text-primary-text [&_a]:underline [&_ul]:flex [&_ul]:flex-col [&_ul]:gap-1.5">
        {block.markdown}
      </Markdown>
    ) : (
      <div key={index} className="overflow-x-auto rounded-xl border-[1.5px] border-border" tabIndex={0} role="region" aria-label="Table, scrolls sideways">
        <table className="w-full min-w-[32rem] border-collapse text-left text-sm">
          <thead className="bg-muted">
            <tr>
              {block.headers.map((header) => (
                <th key={header} scope="col" className="px-3 py-2 font-extrabold">
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, r) => (
              <tr key={r} className="border-t border-border align-top">
                {row.map((cell, c) => (
                  <td key={c} className="px-3 py-2">
                    <Cell text={cell} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    ),
  );
}

/** A table cell: plain text with `code` spans. */
function Cell({ text }: { text: string }) {
  return text.split(/(`[^`]+`)/g).map((part, i) =>
    part.startsWith("`") && part.endsWith("`") ? (
      <code key={i} className="rounded bg-muted px-1 font-mono text-[0.9em]">
        {part.slice(1, -1)}
      </code>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}
