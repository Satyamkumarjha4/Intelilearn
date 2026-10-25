import { Reveal } from "@/components/landing/reveal";

type Props = { id?: string; eyebrow: string; title: string; text: string; children: React.ReactNode };

/** A full-width section of the landing page: a rule, then a heading block, then what the section is about. */
export function Band({ id, eyebrow, title, text, children }: Props) {
  return (
    <section id={id} className="mx-auto w-full max-w-[1180px] px-4">
      <div className="border-t-[1.5px] border-border py-14">
        <Reveal className="max-w-[640px]">
          <span className="font-mono text-[11px] font-medium tracking-widest text-muted-foreground uppercase">{eyebrow}</span>
          <h2 className="mt-1 text-[32px] max-[560px]:text-[26px]">{title}</h2>
          <p className="mt-2.5 text-[16.5px] text-muted-foreground">{text}</p>
        </Reveal>
        {children}
      </div>
    </section>
  );
}
