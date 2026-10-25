import { CheckIcon, PencilIcon, XIcon } from "lucide-react";

import { StatusPill } from "@/components/console/status-pill";
import { Button } from "@/components/ui/button";
import { ModelCatalog, type LastTest } from "@/lib/model-catalog";
import type { ConsoleModel } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = {
  models: readonly ConsoleModel[];
  testing: ReadonlySet<number>;
  now: Date;
  onTest: (id: number) => void;
  onEdit: (model: ConsoleModel) => void;
};

const HEAD = "px-3 py-2 text-left text-[11.5px] font-extrabold tracking-wider whitespace-nowrap text-muted-foreground uppercase";
const WIDE = "hidden md:table-cell";

function Chip({ children }: { children: React.ReactNode }) {
  return <span className="rounded-md bg-muted px-1.5 py-0.5 text-[11px] font-extrabold text-muted-foreground">{children}</span>;
}

function TestResult({ test, testing }: { test: LastTest; testing: boolean }) {
  if (testing) {
    return (
      <span role="status" className="inline-flex items-center gap-1.5 font-bold text-muted-foreground">
        <span aria-hidden="true" className="inline-block size-3 rounded-full border-2 border-primary border-r-transparent motion-safe:animate-spin" />
        Testing…
      </span>
    );
  }
  if (test.state === "nokey" || test.state === "off") return <StatusPill tone="off">{test.label}</StatusPill>;
  if (test.state === "never") return <span className="text-muted-foreground">{test.label}</span>;
  const ok = test.state === "ok";
  return (
    <span title={test.title}>
      <span className={cn("inline-flex items-center gap-1 font-extrabold", ok ? "text-success-text" : "text-destructive-text")}>
        {ok ? <CheckIcon className="size-3.5" aria-hidden="true" /> : <XIcon className="size-3.5" aria-hidden="true" />}
        {test.label}
      </span>{" "}
      {test.detail ? <span className={cn("text-xs", ok ? "font-mono text-muted-foreground" : "break-words text-destructive-text")}>{test.detail}</span> : null}
      <span className="block text-xs font-semibold text-muted-foreground">{test.when}</span>
    </span>
  );
}

/**
 * The models, with what each can do, its size and prices, and how its last test went. Under the medium width the
 * detail folds into a line under the name so the table never scrolls sideways.
 */
export function ModelsTable({ models, testing, now, onTest, onEdit }: Props) {
  return (
    <table className="w-full border-collapse text-[13.5px]">
      <caption className="sr-only">Models, grouped by provider</caption>
      <thead>
        <tr className="border-b-[1.5px]">
          <th scope="col" className={HEAD}>Model</th>
          <th scope="col" className={cn(HEAD, WIDE)}>Can do</th>
          <th scope="col" className={cn(HEAD, WIDE, "text-right")}>Context</th>
          <th scope="col" className={cn(HEAD, WIDE, "text-right")}>$ / M in</th>
          <th scope="col" className={cn(HEAD, WIDE, "text-right")}>$ / M out</th>
          <th scope="col" className={cn(HEAD, WIDE, "text-right")}>Limit</th>
          <th scope="col" className={HEAD}>Last test</th>
          <th scope="col" className={HEAD}><span className="sr-only">Actions</span></th>
        </tr>
      </thead>
      <tbody>
        {models.map((model) => {
          const test = ModelCatalog.lastTest(model, now);
          const isTesting = testing.has(model.id);
          const name = model.label || model.name;
          return (
            <tr key={model.id} className="border-b last:border-b-0 hover:bg-muted">
              <td className="px-3 py-2.5 md:max-w-72">
                <span className="flex items-start gap-1.5 font-mono font-semibold">
                  <i aria-hidden="true" className="mt-1 size-2.5 shrink-0 rounded-[3px]" style={{ background: ModelCatalog.swatch(model.provider) }} />
                  <span className="min-w-0 [overflow-wrap:anywhere] md:truncate" title={model.name}>{name}</span>
                </span>
                <span className="block text-xs font-semibold text-muted-foreground md:truncate">
                  {ModelCatalog.providerName(model.provider)}
                  {model.enabled ? "" : " · switched off"}
                  {model.enabled && !model.api_key_set ? " · unavailable" : ""}
                </span>
                <span className="mt-1 flex flex-wrap gap-1 md:hidden">
                  {ModelCatalog.capabilities(model).map((cap) => <Chip key={cap}>{cap}</Chip>)}
                  <span className="font-mono text-xs text-muted-foreground">
                    {ModelCatalog.context(model.context_window)} · {ModelCatalog.price(model.input_cost_per_mtok)} / {ModelCatalog.price(model.output_cost_per_mtok)}
                  </span>
                </span>
              </td>
              <td className={cn("px-3 py-2.5", WIDE)}>
                <span className="flex flex-wrap gap-1">
                  {ModelCatalog.capabilities(model).map((cap) => <Chip key={cap}>{cap}</Chip>)}
                </span>
              </td>
              <td className={cn("px-3 py-2.5 text-right font-mono text-[12.5px]", WIDE)}>{ModelCatalog.context(model.context_window)}</td>
              <td className={cn("px-3 py-2.5 text-right font-mono text-[12.5px]", WIDE)}>{ModelCatalog.price(model.input_cost_per_mtok)}</td>
              <td className={cn("px-3 py-2.5 text-right font-mono text-[12.5px]", WIDE)}>{ModelCatalog.price(model.output_cost_per_mtok)}</td>
              <td className={cn("px-3 py-2.5 text-right font-mono text-[12.5px] whitespace-nowrap", WIDE)}>{ModelCatalog.limit(model.rpm_limit)}</td>
              <td className="max-w-56 px-3 py-2.5">
                <TestResult test={test} testing={isTesting} />
              </td>
              <td className="px-3 py-2.5 whitespace-nowrap">
                <span className="flex gap-1.5">
                  <Button variant="outline" size="sm" disabled={!ModelCatalog.canTest(model) || isTesting} onClick={() => onTest(model.id)} aria-label={`Test ${name}`}>
                    Test
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => onEdit(model)} aria-label={`Edit ${name}`}>
                    <PencilIcon /> <span className="max-md:sr-only">Edit</span>
                  </Button>
                </span>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
