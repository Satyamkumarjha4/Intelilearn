"use client";

import { CheckBox, NumberBox, StackedField, TextBox } from "@/components/console/field-row";
import { TestimonialForm, type TestimonialProblems } from "@/lib/console-testimonials/testimonial-form";
import type { TestimonialDraft } from "@/lib/console-testimonials/types";

type Props = {
  idPrefix: string;
  draft: TestimonialDraft;
  onChange: (next: TestimonialDraft) => void;
  problems: TestimonialProblems;
  /** Messages the server gave for this form, by field, shown beside the ones found here. */
  refused?: Record<string, string>;
  isSample?: boolean;
};

/** The boxes of a testimonial, for adding one and for editing one. Publishing needs the consent box ticked first. */
export function TestimonialFields({ idPrefix, draft, onChange, problems, refused = {}, isSample = false }: Props) {
  const set = (patch: Partial<TestimonialDraft>) => onChange({ ...draft, ...patch });
  const error = (field: keyof TestimonialProblems) => problems[field] ?? refused[field];
  const why = TestimonialForm.cannotPublish(draft, isSample);
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-3 max-[560px]:grid-cols-1">
        <StackedField id={`${idPrefix}-name`} label="Name" help="As the learner agreed to be shown, for example a first name." error={error("name")}>
          <TextBox id={`${idPrefix}-name`} value={draft.name} onChange={(name) => set({ name })} error={error("name")} />
        </StackedField>
        <StackedField id={`${idPrefix}-context`} label="Who they are" help='For example "Class 12 student".' error={error("context")}>
          <TextBox id={`${idPrefix}-context`} value={draft.context} onChange={(context) => set({ context })} error={error("context")} />
        </StackedField>
      </div>
      <StackedField id={`${idPrefix}-quote`} label="What they said" help={TestimonialForm.count(draft.quote)} error={error("quote")}>
        <textarea
          id={`${idPrefix}-quote`}
          rows={3}
          value={draft.quote}
          onChange={(event) => set({ quote: event.target.value })}
          aria-invalid={error("quote") ? true : undefined}
          aria-describedby={error("quote") ? `${idPrefix}-quote-error` : undefined}
          className="w-full min-w-0 resize-y rounded-[9px] border-[1.5px] bg-card px-2.5 py-1.5 text-[13px] outline-none focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive"
        />
      </StackedField>
      <div className="grid grid-cols-2 items-start gap-3 max-[560px]:grid-cols-1">
        <StackedField id={`${idPrefix}-rating`} label="Stars (optional)" help="1 to 5, or empty for none. No stars are shown without one." error={error("rating")}>
          <NumberBox id={`${idPrefix}-rating`} value={draft.rating} invalid={!!error("rating")} onChange={(rating) => set({ rating })} />
        </StackedField>
        <div className="grid content-start gap-1">
          <span className="text-[13px] font-bold">Permission</span>
          <CheckBox id={`${idPrefix}-consent`} label="The learner agreed to be quoted on the landing page" checked={draft.consent_confirmed} onChange={(consent_confirmed) => set({ consent_confirmed })} />
          <CheckBox id={`${idPrefix}-published`} label="Show it on the landing page" checked={draft.is_published} disabled={!!why && !draft.is_published} onChange={(is_published) => set({ is_published })} />
          {error("is_published") ? (
            <p className="text-xs font-bold text-destructive-text">{error("is_published")}</p>
          ) : why ? (
            <p className="text-xs font-semibold text-muted-foreground">{why}</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
