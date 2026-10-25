"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Trash2Icon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { CheckBox, NumberBox, SelectBox, StackedField, TextBox } from "@/components/console/field-row";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { consoleApi } from "@/lib/console-api";
import { ConsoleFailure } from "@/lib/console-failure";
import { consoleQueries } from "@/lib/console-queries";
import { ModelCatalog } from "@/lib/model-catalog";
import { ModelForm, type ModelFormValues } from "@/lib/model-form";
import type { ConsoleModel, ConsoleProvider } from "@/lib/types";

/** `null` is closed, `"new"` adds a model, a model edits it. */
export type ModelDialogTarget = ConsoleModel | "new" | null;
type Props = { target: ModelDialogTarget; providers: readonly ConsoleProvider[]; onClose: () => void };

const METHODS = [
  { value: "json_schema", label: "JSON schema" },
  { value: "function_calling", label: "Function calling" },
  { value: "json_mode", label: "JSON mode" },
];
const CONTROLS = [
  { value: "none", label: "None" },
  { value: "effort", label: "An effort level" },
  { value: "budget_tokens", label: "A token budget" },
];

export function ModelDialog({ target, providers, onClose }: Props) {
  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-xl overflow-y-auto">
        {target ? <ModelFields key={target === "new" ? "new" : target.id} model={target === "new" ? null : target} providers={providers} onClose={onClose} /> : null}
      </DialogContent>
    </Dialog>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <fieldset className="grid gap-3 rounded-xl border p-3">
      <legend className="px-1 text-[11.5px] font-extrabold tracking-wider text-muted-foreground uppercase">{title}</legend>
      {children}
    </fieldset>
  );
}

function ModelFields({ model, providers, onClose }: { model: ConsoleModel | null; providers: readonly ConsoleProvider[]; onClose: () => void }) {
  const queryClient = useQueryClient();
  const mode = model ? "edit" : "add";
  const [values, setValues] = useState<ModelFormValues>(() => (model ? ModelForm.fromModel(model) : ModelForm.blank(providers[0]?.key ?? "")));
  const [refused, setRefused] = useState<Partial<Record<keyof ModelFormValues, string>>>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [inUse, setInUse] = useState<string | null>(null);

  const errors = { ...(submitted ? ModelForm.errors(values, mode) : {}), ...refused };
  const change = (patch: Partial<ModelFormValues>) => {
    setValues({ ...values, ...patch });
    setRefused((current) => Object.fromEntries(Object.entries(current).filter(([field]) => !(field in patch))));
  };
  const text = (field: keyof ModelFormValues, label: string, options: { help?: string; mono?: boolean; numeric?: boolean } = {}) => (
    <StackedField id={`model-${field}`} label={label} help={options.help} error={errors[field]}>
      {options.numeric ? (
        <NumberBox id={`model-${field}`} width="w-full" value={values[field] as string} invalid={!!errors[field]} onChange={(value) => change({ [field]: value })} />
      ) : (
        <TextBox id={`model-${field}`} mono={options.mono} value={values[field] as string} error={errors[field]} onChange={(value) => change({ [field]: value })} />
      )}
    </StackedField>
  );
  const price = (field: "input_cost_per_mtok" | "output_cost_per_mtok", label: string) => (
    <StackedField id={`model-${field}`} label={label} help="Dollars, blank if unknown." error={errors[field]}>
      <TextBox id={`model-${field}`} mono inputMode="decimal" value={values[field]} error={errors[field]} onChange={(value) => change({ [field]: value })} />
    </StackedField>
  );
  const tick = (field: keyof ModelFormValues, label: string) => (
    <CheckBox id={`model-${field}`} label={label} checked={values[field] as boolean} onChange={(checked) => change({ [field]: checked })} />
  );

  const save = async () => {
    setSubmitted(true);
    if (Object.keys(ModelForm.errors(values, mode)).length) return;
    setSaving(true);
    setFailure(null);
    try {
      if (model) {
        const changes = ModelForm.changes(model, values);
        if (Object.keys(changes).length === 0) return onClose();
        const saved = await consoleApi.updateModel(model.id, changes);
        queryClient.setQueryData<ConsoleModel[]>(consoleQueries.models().queryKey, (rows) => rows?.map((row) => (row.id === saved.id ? saved : row)));
        toast.success(`${saved.label || saved.name} saved.`);
      } else {
        const added = await consoleApi.addModel(ModelForm.newModel(values));
        queryClient.setQueryData<ConsoleModel[]>(consoleQueries.models().queryKey, (rows) => [...(rows ?? []), added]);
        void queryClient.invalidateQueries({ queryKey: consoleQueries.providers().queryKey }); // its models count
        toast.success(`${added.label || added.name} added.`);
      }
      onClose();
    } catch (error) {
      const fields = ModelForm.serverErrors(error);
      setRefused(fields);
      setFailure(Object.keys(fields).length ? null : ConsoleFailure.of(error).message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!model) return;
    try {
      await consoleApi.deleteModel(model.id);
      queryClient.setQueryData<ConsoleModel[]>(consoleQueries.models().queryKey, (rows) => rows?.filter((row) => row.id !== model.id));
      void queryClient.invalidateQueries({ queryKey: consoleQueries.providers().queryKey });
      toast.success(`${model.label || model.name} deleted.`);
      onClose();
    } catch (error) {
      const reason = ModelCatalog.inUse(error);
      setInUse(reason ?? ConsoleFailure.of(error).message);
      toast.error(reason ?? ConsoleFailure.of(error).message);
    }
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle>{model ? `Edit ${model.label || model.name}` : "Add model"}</DialogTitle>
        <DialogDescription>
          {model ? "Changes apply to calls made after you save." : "A model is used only once a step has it in its chain (Model routing)."}
        </DialogDescription>
      </DialogHeader>

      <div className="grid gap-3">
        <Group title="Model">
          {model ? (
            <p className="text-[13px] font-semibold text-muted-foreground">
              Provider: <b className="text-foreground">{ModelCatalog.providerName(model.provider)}</b> (it cannot be changed)
            </p>
          ) : (
            <StackedField id="model-provider" label="Provider" error={errors.provider}>
              <SelectBox
                id="model-provider"
                value={values.provider}
                error={errors.provider}
                onChange={(provider) => change({ provider })}
                options={providers.map((p) => ({ value: p.key, label: ModelCatalog.providerName(p.key) }))}
              />
            </StackedField>
          )}
          {text("name", "Model id", { help: "The id sent to the provider, like gpt-oss-120b.", mono: true })}
          {text("label", "Display name", { help: "Optional. Shown instead of the id." })}
          <div className="flex items-center justify-between gap-3">
            <span id="model-enabled-label" className="text-[13px] font-bold">Use this model</span>
            <Switch aria-labelledby="model-enabled-label" checked={values.enabled} onCheckedChange={(enabled) => change({ enabled })} />
          </div>
        </Group>

        <Group title="Size and price">
          <div className="grid grid-cols-2 gap-3 max-[480px]:grid-cols-1">
            {text("context_window", "Context window", { help: "Tokens it can read.", numeric: true })}
            {text("max_output_tokens", "Longest answer", { help: "Tokens it can write.", numeric: true })}
            {text("rpm_limit", "Requests per minute", { help: "Blank for no limit.", numeric: true })}
            <span aria-hidden="true" className="max-[480px]:hidden" />
            {price("input_cost_per_mtok", "$ per million tokens in")}
            {price("output_cost_per_mtok", "$ per million tokens out")}
          </div>
        </Group>

        <Group title="What it can do">
          <div className="grid grid-cols-2 gap-x-3 gap-y-2 max-[480px]:grid-cols-1">
            {tick("supports_structured_output", "Structured (JSON) output")}
            {tick("supports_tool_calling", "Tool calls")}
            {tick("supports_parallel_tool_calls", "Parallel tool calls")}
            {tick("supports_vision", "Reads images")}
            {tick("supports_reasoning", "Reasoning")}
            {tick("reasoning_disables_sampling", "Reasoning turns off temperature")}
          </div>
          <div className="grid grid-cols-2 gap-3 max-[480px]:grid-cols-1">
            <StackedField id="model-structured_output_method" label="How JSON is asked for">
              <SelectBox id="model-structured_output_method" value={values.structured_output_method} options={METHODS} onChange={(value) => change({ structured_output_method: value as ModelFormValues["structured_output_method"] })} />
            </StackedField>
            <StackedField id="model-reasoning_control" label="How reasoning is set" error={errors.reasoning_control}>
              <SelectBox id="model-reasoning_control" value={values.reasoning_control} error={errors.reasoning_control} options={CONTROLS} onChange={(value) => change({ reasoning_control: value as ModelFormValues["reasoning_control"] })} />
            </StackedField>
          </div>
        </Group>

        <StackedField id="model-default_params" label="Default parameters" help="Sent with every call, like temperature. A JSON object." error={errors.default_params}>
          <textarea
            id="model-default_params"
            value={values.default_params}
            rows={3}
            spellCheck={false}
            aria-invalid={errors.default_params ? true : undefined}
            aria-describedby={errors.default_params ? "model-default_params-error" : undefined}
            onChange={(event) => change({ default_params: event.target.value })}
            className="w-full rounded-[9px] border-[1.5px] bg-card px-2.5 py-1.5 font-mono text-xs outline-none focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive"
          />
        </StackedField>

        {failure ? (
          <Alert variant="destructive">
            <AlertDescription>{failure}</AlertDescription>
          </Alert>
        ) : null}
        {inUse ? (
          <Alert variant="destructive" role="alert">
            <AlertDescription>{inUse}</AlertDescription>
          </Alert>
        ) : null}
      </div>

      <DialogFooter className="sm:justify-between">
        {model ? (
          <Button variant="destructive" disabled={saving} onClick={() => setConfirmingDelete(true)}>
            <Trash2Icon /> Delete
          </Button>
        ) : (
          <span />
        )}
        <span className="flex gap-2">
          <Button variant="outline" disabled={saving} onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={saving} onClick={() => void save()}>
            {saving ? "Saving…" : model ? "Save" : "Add model"}
          </Button>
        </span>
      </DialogFooter>

      {model ? (
        <ConfirmDialog
          open={confirmingDelete}
          onOpenChange={setConfirmingDelete}
          title="Delete this model?"
          description={`${model.label || model.name} is removed from the list. If a step still uses it, it cannot be deleted: take it out of those steps first.`}
          confirmLabel="Delete model"
          cancelLabel="Keep it"
          onConfirm={remove}
        />
      ) : null}
    </>
  );
}
