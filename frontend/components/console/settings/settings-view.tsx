"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/console/error-state";
import { errorId, FieldRow, NumberBox } from "@/components/console/field-row";
import { PageHeader } from "@/components/console/page-header";
import { SaveBar } from "@/components/console/save-bar";
import { WhereLearnersGo } from "@/components/console/settings/where-learners-go";
import { CardSkeleton } from "@/components/console/skeletons";
import { UnsavedChangesGuard } from "@/components/console/unsaved-guard";
import { useConsoleQuery } from "@/components/console/use-console-query";
import { Switch } from "@/components/ui/switch";
import { consoleApi } from "@/lib/console-api";
import { ConsoleFailure } from "@/lib/console-failure";
import { consoleQueries } from "@/lib/console-queries";
import { FlowBands } from "@/lib/flow-bands";
import { type FlowErrors, type FlowForm, FlowSettingsForm } from "@/lib/flow-settings-form";
import type { FlowSettingsValues } from "@/lib/types";
import { cn } from "@/lib/utils";

const SOURCES = [
  { id: "wikimedia", label: "Wikimedia Commons", help: undefined },
  { id: "openverse", label: "Openverse", help: undefined },
  { id: "giphy", label: "Giphy", help: "Needs GIPHY_API_KEY" },
];
const LICENCES = [
  { id: "cc0", label: "CC0" },
  { id: "pdm", label: "Public domain" },
  { id: "cc-by", label: "CC BY" },
  { id: "cc-by-sa", label: "CC BY-SA" },
  { id: "cc-by-nc", label: "CC BY-NC" },
];
const SOURCE_IDS = SOURCES.map((source) => source.id);
const LICENCE_IDS = LICENCES.map((licence) => licence.id);

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="rounded-2xl border bg-card shadow-card">
      <h2 className="px-[18px] pt-4 font-sans text-base font-extrabold">{title}</h2>
      <div className="px-[18px] pt-1 pb-3">{children}</div>
    </section>
  );
}

/** The Lesson settings page: the form, the live "where learners go" panel, and the save bar. */
export function SettingsView() {
  const queryClient = useQueryClient();
  const { data: saved, error, isPending, refetch } = useConsoleQuery(consoleQueries.flowSettings());
  const [edited, setEdited] = useState<FlowForm | null>(null);
  const [refused, setRefused] = useState<FlowErrors>({});
  const [saving, setSaving] = useState(false);

  const header = <PageHeader title="Lesson settings" description="How quick checks, lessons and quality checks behave. Each lesson keeps the settings it started with." />;
  if (error && !saved) return <>{header}<ErrorState message="The lesson settings could not be loaded." onRetry={() => void refetch()} /></>;
  if (isPending || !saved) {
    return (
      <div aria-busy="true">
        {header}
        <div className="grid gap-4"><CardSkeleton height={160} /><CardSkeleton height={120} /></div>
      </div>
    );
  }

  const form = edited ?? FlowSettingsForm.fromSettings(saved);
  const dirty = FlowSettingsForm.dirty(saved, form);
  const problems = { ...FlowSettingsForm.errors(form), ...refused };
  const invalid = Object.keys(problems).length > 0;

  const change = (patch: Partial<FlowForm>) => {
    setEdited({ ...form, ...patch });
    setRefused((current) => Object.fromEntries(Object.entries(current).filter(([field]) => !(field in patch))));
  };
  const discard = () => {
    setEdited(null);
    setRefused({});
  };
  const save = async () => {
    setSaving(true);
    try {
      const result = await consoleApi.updateFlowSettings(FlowSettingsForm.patch(saved, form));
      queryClient.setQueryData(consoleQueries.flowSettings().queryKey, result);
      discard();
      toast.success("Settings saved. New lessons will use them.");
    } catch (failure) {
      const fields = FlowSettingsForm.serverErrors(failure);
      setRefused(fields);
      toast.error(Object.keys(fields).length ? "Some settings were refused. See the notes beside them." : ConsoleFailure.of(failure).message);
    } finally {
      setSaving(false);
    }
  };

  const numberRow = (field: keyof FlowForm & keyof FlowSettingsValues, label: string, help?: string) => (
    <FieldRow htmlFor={field} label={label} help={help} error={problems[field]}>
      <NumberBox id={field} value={form[field] as string} invalid={!!problems[field]} onChange={(value) => change({ [field]: value })} />
    </FieldRow>
  );
  const switchRow = (id: string, label: string, help: string | undefined, checked: boolean, onChange: (next: boolean) => void) => (
    <FieldRow labelId={`${id}-label`} label={label} help={help}>
      <Switch aria-labelledby={`${id}-label`} checked={checked} onCheckedChange={onChange} />
    </FieldRow>
  );
  const testError = problems.final_test_min ?? problems.final_test_max;
  const bands = FlowBands.of(FlowSettingsForm.numbers(saved, form));

  return (
    <div>
      {header}
      <div className="grid items-start gap-4 min-[1000px]:grid-cols-[minmax(0,1fr)_320px]">
        <div className="grid min-w-0 gap-4 max-[1000px]:order-2">
          <Section title="Quick check">
            {numberRow("diagnostic_questions_per_band", "Questions per difficulty level", `${FlowBands.LEVELS} levels, so the quick check has ${FlowBands.LEVELS} × this many questions`)}
            {numberRow("prereq_trigger_max_correct", 'Send to "foundations first" at or below', "Correct answers out of the total")}
            {numberRow("prerequisite_question_count", "Foundations check length", "Questions in the prerequisite check")}
            {switchRow("mastery", "Study sheets only for a perfect score", "Off: a score of total − 1 also counts as mastered", form.mastery_requires_all_correct, (next) => change({ mastery_requires_all_correct: next }))}
          </Section>

          <Section title="Lesson">
            <FieldRow htmlFor="final_test_min" label="Final test questions" help="Minimum and maximum" error={testError}>
              <NumberBox id="final_test_min" ariaLabel="Minimum test questions" width="w-[70px]" value={form.final_test_min} invalid={!!problems.final_test_min} errorFor={errorId("final_test_min")} onChange={(value) => change({ final_test_min: value })} />
              <span aria-hidden="true">–</span>
              <NumberBox id="final_test_max" ariaLabel="Maximum test questions" width="w-[70px]" value={form.final_test_max} invalid={!!problems.final_test_max} errorFor={errorId("final_test_min")} onChange={(value) => change({ final_test_max: value })} />
            </FieldRow>
            {numberRow("max_interactives_per_page", "Interactives per page", "Graphs, simulations, diagrams, code")}
          </Section>

          <Section title="Quality checks">
            {numberRow("alignment_min_score", "Minimum level-fit score", "The judge scores 1–5 how well a lesson fits the learner")}
            {numberRow("alignment_max_rounds", "Rewrite rounds", "Times a lesson can be rewritten to fit better")}
            {numberRow("render_check_max_rounds", "Render-check rounds", "Fix attempts when a page fails in the test browser")}
            {numberRow("max_auto_runtime_repairs", "Automatic crash repairs", "Per lesson, when a page breaks for a learner")}
          </Section>

          <Section title="Images and media">
            {SOURCES.map((source) => (
              <Fragment key={source.id}>
                {switchRow(`source-${source.id}`, source.label, source.help, form.media_sources.includes(source.id), () =>
                  change({ media_sources: FlowSettingsForm.toggle(form.media_sources, source.id, SOURCE_IDS) }),
                )}
              </Fragment>
            ))}
            <FieldRow labelId="licences-label" label="Allowed licences" error={undefined}>
              <div role="group" aria-labelledby="licences-label" className="flex flex-wrap justify-end gap-1.5 max-[560px]:justify-start">
                {LICENCES.map((licence) => {
                  const on = form.allowed_media_licenses.includes(licence.id);
                  return (
                    <button
                      key={licence.id}
                      type="button"
                      aria-pressed={on}
                      onClick={() => change({ allowed_media_licenses: FlowSettingsForm.toggle(form.allowed_media_licenses, licence.id, LICENCE_IDS) })}
                      className={cn(
                        "rounded-full border-[1.5px] px-2.5 py-1 text-[12.5px] font-extrabold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                        on ? "border-primary bg-primary-soft text-primary-text" : "bg-card text-muted-foreground hover:bg-muted",
                      )}
                    >
                      {licence.label}
                    </button>
                  );
                })}
              </div>
            </FieldRow>
            {problems.media_sources || problems.allowed_media_licenses ? (
              <p role="alert" className="text-xs font-bold text-destructive-text">
                {problems.media_sources ?? problems.allowed_media_licenses}
              </p>
            ) : null}
          </Section>
        </div>

        <div className="max-[1000px]:order-1">
          <WhereLearnersGo view={bands} unsaved={dirty.length > 0} />
        </div>
      </div>

      <SaveBar
        visible={dirty.length > 0}
        note={invalid ? "Fix the highlighted settings to save." : "New lessons will use these settings."}
        saveLabel="Save settings"
        saving={saving}
        saveDisabled={invalid}
        onDiscard={discard}
        onSave={() => void save()}
      />
      <UnsavedChangesGuard dirty={dirty.length > 0} />
    </div>
  );
}
