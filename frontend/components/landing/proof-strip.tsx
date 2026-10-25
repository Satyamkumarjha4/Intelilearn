import { DownloadIcon, GlobeIcon, ImageIcon, ShieldCheckIcon, type LucideIcon } from "lucide-react";

import { Reveal } from "@/components/landing/reveal";
import { PROOF_ITEMS, type ProofIcon, type Tone } from "@/lib/landing-content";
import { cn } from "@/lib/utils";

const ICON: Record<ProofIcon, LucideIcon> = { globe: GlobeIcon, shield: ShieldCheckIcon, image: ImageIcon, download: DownloadIcon };
const TONE: Record<Tone, string> = { primary: "bg-primary-soft text-primary-text", marigold: "bg-marigold-soft text-marigold-text", insight: "bg-insight-soft text-insight-text" };

/** Four small reasons to trust it, in a row. */
export function ProofStrip() {
  return (
    <section aria-label="Why you can trust Socra" className="mx-auto w-full max-w-[1180px] px-4">
      <div className="border-t-[1.5px] border-border py-14">
        <ul className="grid grid-cols-4 gap-5 max-[900px]:grid-cols-2 max-[560px]:grid-cols-1">
          {PROOF_ITEMS.map(({ icon, tone, title, text }, index) => {
            const Icon = ICON[icon];
            return (
              <li key={title}>
                <Reveal index={index} className="flex items-start gap-3">
                  <span className={cn("grid size-[42px] shrink-0 place-items-center rounded-[13px]", TONE[tone])}>
                    <Icon className="size-5" strokeWidth={2.3} aria-hidden="true" />
                  </span>
                  <div>
                    <b className="block text-[15px]">{title}</b>
                    <p className="text-[13.5px] text-muted-foreground">{text}</p>
                  </div>
                </Reveal>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}
