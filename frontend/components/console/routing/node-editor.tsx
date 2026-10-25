"use client";

import { InfoIcon, PlusIcon } from "lucide-react";
import { useState } from "react";

import { BindingList } from "@/components/console/routing/binding-list";
import { FieldRow, NumberBox, SelectBox } from "@/components/console/field-row";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { ModelCatalog } from "@/lib/model-catalog";
import { RoutingDraft } from "@/lib/routing-draft";
import { RoutingView } from "@/lib/routing-view";
import type { ConsoleModel, Effort, NodeRouting } from "@/lib/types";

type Props = {
  node: NodeRouting;
  models: readonly ConsoleModel[];
  /** Why the last save of this step was refused. */
  failures: readonly string[];
  onChange: (node: NodeRouting) => void;
};

const EFFORTS: { value: Effort; label: string }[] = [
  { value: "none", label: "none" },
  { value: "low", label: "low" },
  { value: "medium", label: "medium" },
  { value: "high", label: "high" },
];
const MAX = 32767;

/** A whole number from 1 up, or null. */
function whole(text: string): number | null {
  const trimmed = text.trim();
  return /^\d+$/.test(trimmed) && Number(trimmed) >= 1 && Number(trimmed) <= MAX ? Number(trimmed) : null;
}

/**
 * A number the step keeps, typed as text: what is typed on the way to a number is not one yet, so the step changes
 * only when the text is a valid number, and a note says so while it is not.
 */
function CountField({ id, label, help, value, onCommit }: { id: string; label: string; help: string; value: number; onCommit: (value: number) => void }) {
  const [typed, setTyped] = useState<string | null>(null);
  // Text that is still a valid number for a different value is stale (the step was reset), so the step's value wins.
  const parsed = typed === null ? null : whole(typed);
  const shown = typed !== null && (parsed === null || parsed === value) ? typed : String(value);
  const invalid = typed !== null && parsed === null;
  return (
    <FieldRow htmlFor={id} label={label} help={help} error={invalid ? `Enter a whole number from 1 to ${MAX}.` : undefined}>
      <NumberBox
        id={id}
        value={shown}
        invalid={invalid}
        onChange={(text) => {
          setTyped(text);
          const next = whole(text);
          if (next !== null) onCommit(next);
        }}
      />
    </FieldRow>
  );
}

/** The editor of one step. It changes the local copy only; saving is the page's job. */
export function NodeEditor({ node, models, failures, onChange }: Props) {
  const [chosen, setChosen] = useState("");
  const fallbacks = RoutingDraft.fallbacks(node, models);
  const byId = new Map(models.map((model) => [model.id, model]));
  const pick = fallbacks.find((model) => String(model.id) === chosen) ?? fallbacks[0];
  const required = RoutingView.requiredReason(node);

  return (
    <div>
      <div className="border-b-[1.5px] px-[18px] py-4">
        <h2 className="font-mono text-[15px] font-semibold [overflow-wrap:anywhere]">{node.key}</h2>
        <p className="mt-0.5 text-muted-foreground">{node.description}</p>
      </div>
      <div className="px-[18px] pt-1 pb-4">
        {failures.length ? (
          <Alert variant="destructive" className="mt-3">
            <AlertDescription>
              <b className="block">This step was not saved:</b>
              <ul className="mt-1 list-disc pl-4">
                {failures.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        ) : null}

        <FieldRow labelId="node-enabled-label" label="Step enabled" help={required ?? "Optional step: lessons still build without it"}>
          <Switch aria-labelledby="node-enabled-label" checked={node.enabled} disabled={!node.optional} onCheckedChange={(enabled) => onChange({ ...node, enabled })} />
        </FieldRow>
        <FieldRow htmlFor="node-effort" label="Reasoning effort" help="Higher is slower and costs more">
          <SelectBox id="node-effort" value={node.reasoning_effort} options={EFFORTS} className="w-28" onChange={(value) => onChange({ ...node, reasoning_effort: value as Effort })} />
        </FieldRow>
        <CountField id="node-attempts" label="Attempts before failing" help="Across the whole chain" value={node.max_attempts} onCommit={(max_attempts) => onChange({ ...node, max_attempts })} />
        <CountField id="node-timeout" label="Timeout per call" help="Seconds" value={node.timeout_s} onCommit={(timeout_s) => onChange({ ...node, timeout_s })} />

        <h3 className="mt-4 mb-2 font-sans text-xs font-extrabold tracking-wider text-muted-foreground uppercase">Model order · drag to reorder</h3>
        <BindingList node={node} models={byId} onChange={onChange} />

        {fallbacks.length ? (
          <div className="mt-2 flex gap-2">
            <SelectBox
              id="node-add-fallback"
              ariaLabel="Model to add as a fallback"
              className="flex-1"
              value={String(pick?.id ?? "")}
              onChange={setChosen}
              options={fallbacks.map((model) => ({ value: String(model.id), label: `${model.label || model.name} · ${ModelCatalog.providerName(model.provider)}` }))}
            />
            <Button
              variant="outline"
              onClick={() => {
                if (pick) onChange(RoutingDraft.add(node, pick));
                setChosen("");
              }}
            >
              <PlusIcon /> Add fallback
            </Button>
          </div>
        ) : (
          <p className="mt-2 text-xs font-semibold text-muted-foreground">No other model can be added: each one that is switched on and has its provider&apos;s key set is already here.</p>
        )}

        <p className="mt-3.5 flex items-start gap-2.5 rounded-xl bg-marigold-soft px-3 py-2.5 text-[12.5px] font-bold text-marigold-text">
          <InfoIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          Lessons already running keep the routing they started with.
        </p>
      </div>
    </div>
  );
}
