import { PencilIcon } from "lucide-react";

import { StatusPill } from "@/components/console/status-pill";
import { Button } from "@/components/ui/button";
import { ModelCatalog } from "@/lib/model-catalog";
import type { ConsoleProvider } from "@/lib/types";

/** One provider: its colour, whether its key is set (never the key), its limit, how many models it has and what it cost. */
export function ProviderCard({ provider, onEdit }: { provider: ConsoleProvider; onEdit: () => void }) {
  const card = ModelCatalog.providerCard(provider);
  return (
    <section aria-label={card.name} className="grid content-start gap-2 rounded-2xl border bg-card p-4 shadow-card">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex min-w-0 items-center gap-1.5 font-sans text-[15px] font-extrabold">
          <i aria-hidden="true" className="size-2.5 shrink-0 rounded-[3px]" style={{ background: card.swatch }} />
          <span className="truncate">{card.name}</span>
        </h3>
        <StatusPill tone={card.status.tone}>{card.status.label}</StatusPill>
      </div>
      <p className="font-mono text-xs break-all text-muted-foreground">{card.secret || "—"}</p>
      <dl className="grid gap-1">
        {card.rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-2 text-[12.5px] font-bold text-muted-foreground">
            <dt>{label}</dt>
            <dd className="font-mono text-foreground">{value}</dd>
          </div>
        ))}
      </dl>
      <Button variant="outline" size="sm" className="mt-1 justify-self-start" onClick={onEdit} aria-label={`Edit ${card.name}`}>
        <PencilIcon /> Edit
      </Button>
    </section>
  );
}
