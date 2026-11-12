import Link from "next/link";

import { Logo } from "@/components/brand/logo";
import { AuthRules, type Mode } from "@/lib/auth-form";

/** The brand side: a strip on a phone, a full panel (headline, the three steps, tilted cards) from 900px. */
export function BrandPanel({ mode }: { mode: Mode }) {
  return (
    <aside className="relative flex flex-col gap-6 overflow-hidden bg-primary-action p-6 text-primary-foreground sm:p-9 min-[900px]:justify-between">
      <Link href="/" aria-label="Socra home" className="w-fit rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-primary-foreground/60">
        <Logo tone="marigold" size="md" />
      </Link>

      <div className="relative z-10 flex flex-col gap-6">
        <p className="font-heading text-2xl leading-tight font-semibold min-[900px]:text-4xl">{AuthRules.COPY[mode].panel}</p>
        <ol className="flex flex-col gap-3 font-bold max-[899px]:hidden">
          {AuthRules.STEPS.map((step, index) => (
            <li key={step} className="flex items-center gap-3">
              <span className="grid size-8 shrink-0 place-items-center rounded-full bg-primary-action-pressed font-mono text-sm">{index + 1}</span>
              {step}
            </li>
          ))}
        </ol>
      </div>

      <div aria-hidden="true" className="pointer-events-none absolute -right-24 -bottom-20 h-56 w-72 max-[899px]:hidden">
        <div className="absolute right-6 bottom-12 h-32 w-52 -rotate-[8deg] rounded-2xl bg-primary-foreground/15 p-4">
          <div className="mb-3 h-2.5 w-24 rounded-full bg-primary-foreground/40" />
          <div className="flex flex-col gap-2">
            <div className="h-6 rounded-lg bg-primary-foreground/25" />
            <div className="h-6 rounded-lg bg-primary-foreground/25" />
          </div>
        </div>
        <div className="absolute right-0 bottom-0 h-28 w-48 rotate-[6deg] rounded-2xl bg-primary-foreground/20 p-4">
          <div className="mb-3 h-2.5 w-20 rounded-full bg-primary-foreground/50" />
          <div className="h-2 w-36 rounded-full bg-primary-foreground/30" />
        </div>
      </div>
    </aside>
  );
}
