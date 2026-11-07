"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/console/error-state";
import { CheckBox, FieldRow, NumberBox, TextBox } from "@/components/console/field-row";
import { PageHeader } from "@/components/console/page-header";
import { SaveBar } from "@/components/console/save-bar";
import { CardSkeleton } from "@/components/console/skeletons";
import { UnsavedChangesGuard } from "@/components/console/unsaved-guard";
import { useConsoleQuery } from "@/components/console/use-console-query";
import { consoleApi } from "@/lib/console-api";
import { type Draft, FieldDraft } from "@/lib/console-credits/field-draft";
import { PriceForm, type PriceDraft } from "@/lib/console-credits/price-draft";
import { creditQueries } from "@/lib/console-credits/queries";
import type { ConsolePlan, ConsolePrice } from "@/lib/console-credits/types";
import { ConsoleFailure } from "@/lib/console-failure";
import { ConsoleFormat } from "@/lib/console-format";

const PLAN_FIELDS: { field: keyof Omit<ConsolePlan, "key" | "name" | "active">; label: string; help: string }[] = [
  { field: "credits", label: "Credits each period", help: "0 for one-time credits: the buyer chooses" },
  { field: "period_days", label: "Days a period lasts", help: "For one-time credits, how long they last" },
  { field: "price_paise", label: "Price in paise", help: "100 paise = ₹1, tax included. One-time credits: the price of one credit" },
  { field: "max_quantity", label: "Most bought at once", help: "Weeks of Weekly Pro; 1 for the rest" },
  { field: "sort", label: "Order on the buy page", help: "Smaller first" },
];

function humanize(key: string): string {
  const words = key.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="rounded-2xl border bg-card shadow-card">
      <h2 className="px-[18px] pt-4 font-sans text-base font-extrabold">{title}</h2>
      {description ? <p className="px-[18px] text-[13px] font-semibold text-muted-foreground">{description}</p> : null}
      <div className="px-[18px] pt-1 pb-3">{children}</div>
    </section>
  );
}

function PriceRow({ price, boxes, errors, onChange }: { price: ConsolePrice; boxes: { credits: string; label: string }; errors?: { credits?: string; label?: string }; onChange: (next: { credits: string; label: string }) => void }) {
  const id = `price-${price.key}`;
  return (
    <div className="border-b border-border/60 py-2.5 last:border-b-0">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 max-[560px]:grid-cols-1">
        <div className="min-w-0">
          <span className="font-mono text-[12.5px] font-bold">{price.key}</span>
          {!price.available ? <span className="ml-2 rounded-md bg-destructive-soft px-1.5 py-px text-[11px] font-extrabold text-destructive-text">Unavailable: no live price</span> : null}
          <div className="mt-1 max-w-md">
            <TextBox id={`${id}-label`} value={boxes.label} error={errors?.label} onChange={(label) => onChange({ ...boxes, label })} />
          </div>
        </div>
        <div className="flex items-center justify-end gap-1.5 max-[560px]:justify-start">
          <label htmlFor={`${id}-credits`} className="sr-only">
            Credits for {price.key}
          </label>
          <NumberBox id={`${id}-credits`} value={boxes.credits} invalid={!!errors?.credits} onChange={(credits) => onChange({ ...boxes, credits })} />
          <span className="text-xs font-bold text-muted-foreground">credits</span>
        </div>
      </div>
      {errors?.credits ? (
        <p id={`${id}-credits-error`} className="mt-1 text-xs font-bold text-destructive-text">
          {errors.credits}
        </p>
      ) : null}
      {price.history.length > 1 ? (
        <details className="mt-1.5 text-[12.5px] text-muted-foreground">
          <summary className="cursor-pointer font-bold">History ({price.history.length} prices)</summary>
          <ul className="mt-1 grid gap-0.5 font-semibold">
            {price.history.map((row, index) => (
              <li key={index}>
                {row.credits} credits{row.active ? " (live)" : ""} · “{row.label}” · {row.updated_by || "seed"} · {ConsoleFormat.dayLong(row.updated_at)}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

/** Credits & prices: what things cost (with each price's history), the plans, and the credit rules. One save bar, like Lesson settings. */
export function CreditsView() {
  const queryClient = useQueryClient();
  const { data: saved, error, isPending, refetch } = useConsoleQuery(creditQueries.config());
  const [prices, setPrices] = useState<PriceDraft | null>(null);
  const [plans, setPlans] = useState<Record<string, Draft>>({});
  const [settings, setSettings] = useState<Draft | null>(null);
  const [refused, setRefused] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const header = <PageHeader title="Credits & prices" description="What things cost, what plans give, and how credits are earned. A price edit adds a row, so the next reserve uses it and history is kept." />;
  if (error && !saved) return <>{header}<ErrorState message="The credit settings could not be loaded." onRetry={() => void refetch()} /></>;
  if (isPending || !saved) {
    return (
      <div aria-busy="true">
        {header}
        <div className="grid gap-4"><CardSkeleton height={220} /><CardSkeleton height={160} /></div>
      </div>
    );
  }

  const priceDraft = prices ?? PriceForm.from(saved.prices);
  const priceDirty = PriceForm.dirty(saved.prices, priceDraft);
  const priceErrors = PriceForm.errors(saved.prices, priceDraft);
  const settingsSaved = saved.settings;
  const settingsDraft = settings ?? FieldDraft.from(settingsSaved);
  const settingsDirty = FieldDraft.dirty(settingsSaved, settingsDraft);
  const settingsErrors = FieldDraft.errors(settingsSaved, settingsDraft);
  const planState = saved.plans.map((plan) => {
    const editable = Object.fromEntries(Object.entries(plan).filter(([field]) => field !== "key")) as Record<string, number | boolean | string>;
    const draft = plans[plan.key] ?? FieldDraft.from(editable);
    return { plan, editable, draft, dirty: FieldDraft.dirty(editable, draft), errors: FieldDraft.errors(editable, draft) };
  });

  const dirtyCount = priceDirty.length + settingsDirty.length + planState.reduce((sum, row) => sum + (row.dirty.length ? 1 : 0), 0);
  const invalid = Object.keys(priceErrors).length > 0 || Object.keys(settingsErrors).length > 0 || planState.some((row) => Object.keys(row.errors).length > 0);
  const summary = [...priceDirty, ...planState.filter((row) => row.dirty.length).map((row) => row.plan.key), ...(settingsDirty.length ? ["settings"] : [])].join(", ");

  const discard = () => {
    setPrices(null);
    setPlans({});
    setSettings(null);
    setRefused({});
  };

  const save = async () => {
    setSaving(true);
    const problems: Record<string, string> = {};
    try {
      for (const change of PriceForm.changes(saved.prices, priceDraft)) {
        try {
          await consoleApi.revisePrice(change.key, change.body);
        } catch (failure) {
          problems[`price.${change.key}`] = ConsoleFailure.of(failure).lines({}).join(" ");
        }
      }
      for (const row of planState.filter((r) => r.dirty.length)) {
        try {
          await consoleApi.updatePlan(row.plan.key, FieldDraft.patch(row.editable, row.draft) as Partial<Omit<ConsolePlan, "key">>);
        } catch (failure) {
          problems[`plan.${row.plan.key}`] = ConsoleFailure.of(failure).lines({}).join(" ");
        }
      }
      if (settingsDirty.length) {
        try {
          await consoleApi.updateCreditSettings(FieldDraft.patch(settingsSaved, settingsDraft) as Record<string, number>);
        } catch (failure) {
          problems.settings = ConsoleFailure.of(failure).lines({}).join(" ");
        }
      }
      await queryClient.invalidateQueries({ queryKey: creditQueries.config().queryKey });
      if (Object.keys(problems).length) {
        setRefused(problems);
        toast.error("Some changes were refused. See the notes under them; the rest were saved.");
      } else {
        discard();
        toast.success("Saved. The next reserve and the next purchase use the new values.");
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      {header}
      <div className="grid gap-4">
        <Section title="Prices" description="Credits each action costs, in the words a learner sees on their quote.">
          {saved.prices.map((price) => (
            <div key={price.key}>
              <PriceRow price={price} boxes={priceDraft[price.key]} errors={priceErrors[price.key]} onChange={(next) => setPrices({ ...priceDraft, [price.key]: next })} />
              {refused[`price.${price.key}`] ? <p role="alert" className="pb-2 text-xs font-bold text-destructive-text">{refused[`price.${price.key}`]}</p> : null}
            </div>
          ))}
        </Section>

        <Section title="Plans" description="What can be bought. An edit changes what is bought next; a purchase already made keeps what it cost and what it gives.">
          {planState.map(({ plan, draft, errors }) => {
            const set = (patch: Draft) => setPlans({ ...plans, [plan.key]: { ...draft, ...patch } });
            return (
              <fieldset key={plan.key} className="border-b border-border/60 py-2 last:border-b-0">
                <legend className="font-heading text-[15px] font-semibold">{plan.key}</legend>
                <FieldRow htmlFor={`plan-${plan.key}-name`} label="Name" error={errors.name}>
                  <TextBox id={`plan-${plan.key}-name`} value={draft.name as string} onChange={(name) => set({ name })} />
                </FieldRow>
                {PLAN_FIELDS.map(({ field, label, help }) => (
                  <FieldRow key={field} htmlFor={`plan-${plan.key}-${field}`} label={label} help={help} error={errors[field]}>
                    <NumberBox id={`plan-${plan.key}-${field}`} value={draft[field] as string} invalid={!!errors[field]} onChange={(value) => set({ [field]: value })} />
                  </FieldRow>
                ))}
                <FieldRow labelId={`plan-${plan.key}-active-label`} label="Offered" help="Off: not offered. Purchases already made are not affected.">
                  <CheckBox id={`plan-${plan.key}-active`} label="On sale" checked={draft.active === true} onChange={(active) => set({ active })} />
                </FieldRow>
                {refused[`plan.${plan.key}`] ? <p role="alert" className="text-xs font-bold text-destructive-text">{refused[`plan.${plan.key}`]}</p> : null}
              </fieldset>
            );
          })}
        </Section>

        <Section title="Credit rules" description="Amounts and windows. Whole numbers; the server checks the limits.">
          {Object.keys(settingsSaved).map((field) => (
            <FieldRow key={field} htmlFor={`setting-${field}`} label={humanize(field)} error={settingsErrors[field]}>
              <NumberBox id={`setting-${field}`} value={settingsDraft[field] as string} invalid={!!settingsErrors[field]} onChange={(value) => setSettings({ ...settingsDraft, [field]: value })} />
            </FieldRow>
          ))}
          {refused.settings ? <p role="alert" className="text-xs font-bold text-destructive-text">{refused.settings}</p> : null}
        </Section>
      </div>

      <SaveBar
        visible={dirtyCount > 0}
        summary={summary}
        note={invalid ? "Fix the highlighted values to save." : "Each change is written to the change log."}
        saveLabel="Save changes"
        saving={saving}
        saveDisabled={invalid}
        onDiscard={discard}
        onSave={() => void save()}
      />
      <UnsavedChangesGuard dirty={dirtyCount > 0} />
    </div>
  );
}
