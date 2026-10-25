"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { NumberBox, StackedField, TextBox } from "@/components/console/field-row";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { consoleApi } from "@/lib/console-api";
import { ConsoleFailure } from "@/lib/console-failure";
import { consoleQueries } from "@/lib/console-queries";
import { ModelCatalog } from "@/lib/model-catalog";
import { ProviderForm, type ProviderFormValues } from "@/lib/model-form";
import type { ConsoleProvider } from "@/lib/types";

type Props = { provider: ConsoleProvider | null; onClose: () => void };

/** Edit a provider: its rate limit, its address (where it takes one) and whether it is used. Its key stays in the server's environment. */
export function ProviderDialog({ provider, onClose }: Props) {
  return (
    <Dialog open={provider !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md">{provider ? <ProviderFields key={provider.key} provider={provider} onClose={onClose} /> : null}</DialogContent>
    </Dialog>
  );
}

function ProviderFields({ provider, onClose }: { provider: ConsoleProvider; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [values, setValues] = useState<ProviderFormValues>(() => ProviderForm.fromProvider(provider));
  const [refused, setRefused] = useState<Partial<Record<keyof ProviderFormValues, string>>>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [saving, setSaving] = useState(false);
  const name = ModelCatalog.providerName(provider.key);

  const errors = { ...(submitted ? ProviderForm.errors(provider, values) : {}), ...refused };
  const change = (patch: Partial<ProviderFormValues>) => {
    setValues({ ...values, ...patch });
    setRefused((current) => Object.fromEntries(Object.entries(current).filter(([field]) => !(field in patch))));
  };

  const save = async () => {
    setSubmitted(true);
    if (Object.keys(ProviderForm.errors(provider, values)).length) return;
    const changes = ProviderForm.changes(provider, values);
    if (Object.keys(changes).length === 0) return onClose();
    setSaving(true);
    setFailure(null);
    try {
      const saved = await consoleApi.updateProvider(provider.key, changes);
      queryClient.setQueryData<ConsoleProvider[]>(consoleQueries.providers().queryKey, (rows) => rows?.map((row) => (row.key === saved.key ? saved : row)));
      toast.success(`${name} saved.`);
      onClose();
    } catch (error) {
      const fields = ProviderForm.serverErrors(error);
      setRefused(fields);
      setFailure(Object.keys(fields).length ? null : ConsoleFailure.of(error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle>Edit {name}</DialogTitle>
        <DialogDescription>
          {provider.api_key_env ? (
            <>
              The API key stays in the server&apos;s environment as <span className="font-mono">{provider.api_key_env}</span> and is never shown here.
            </>
          ) : (
            "This provider needs no API key."
          )}
        </DialogDescription>
      </DialogHeader>
      <div className="grid gap-3">
        <StackedField id="provider-rpm" label="Requests per minute" help="Leave blank for no limit. Lessons wait rather than go over it." error={errors.rpm_limit}>
          <NumberBox id="provider-rpm" value={values.rpm_limit} invalid={!!errors.rpm_limit} width="w-full" onChange={(rpm_limit) => change({ rpm_limit })} />
        </StackedField>
        {ProviderForm.takesBaseUrl(provider) ? (
          <StackedField id="provider-url" label="Address" help="Where this provider answers." error={errors.base_url}>
            <TextBox id="provider-url" mono inputMode="url" value={values.base_url} error={errors.base_url} onChange={(base_url) => change({ base_url })} />
          </StackedField>
        ) : null}
        <div className="flex items-center justify-between gap-3">
          <span id="provider-enabled-label" className="text-[13px] font-bold">
            Use this provider
          </span>
          <Switch aria-labelledby="provider-enabled-label" checked={values.enabled} onCheckedChange={(enabled) => change({ enabled })} />
        </div>
        {failure ? (
          <Alert variant="destructive">
            <AlertDescription>{failure}</AlertDescription>
          </Alert>
        ) : null}
      </div>
      <DialogFooter>
        <Button variant="outline" disabled={saving} onClick={onClose}>
          Cancel
        </Button>
        <Button disabled={saving} onClick={() => void save()}>
          {saving ? "Saving…" : "Save"}
        </Button>
      </DialogFooter>
    </>
  );
}
