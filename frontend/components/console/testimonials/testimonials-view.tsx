"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowDownIcon, ArrowUpIcon, EyeIcon, EyeOffIcon, MessageSquareQuoteIcon, PencilIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/console/empty-state";
import { ErrorState } from "@/components/console/error-state";
import { PageHeader } from "@/components/console/page-header";
import { CardSkeleton } from "@/components/console/skeletons";
import { TestimonialFields } from "@/components/console/testimonials/testimonial-fields";
import { useConsoleQuery } from "@/components/console/use-console-query";
import { Button } from "@/components/ui/button";
import { consoleApi } from "@/lib/console-api";
import { ConsoleFailure } from "@/lib/console-failure";
import { testimonialQueries } from "@/lib/console-testimonials/queries";
import { TestimonialForm } from "@/lib/console-testimonials/testimonial-form";
import type { ConsoleTestimonial, TestimonialDraft } from "@/lib/console-testimonials/types";

const LABELS = { name: "Name", context: "Who they are", quote: "What they said", rating: "Stars", is_published: "Publishing", consent_confirmed: "Permission" };

/** Fields the server refused, one message each, to show beside the boxes. */
function refusals(failure: unknown): Record<string, string> {
  const { fields, message } = ConsoleFailure.of(failure);
  const found = Object.fromEntries(Object.entries(fields).map(([field, messages]) => [field, messages.join(" ")]));
  return Object.keys(found).length ? found : { is_published: message };
}

/** Testimonials: the quotes of "What learners say" on the landing page. Add, edit, reorder, publish and delete; every change is in the change log. */
export function TestimonialsView() {
  const queryClient = useQueryClient();
  const { data, error, isPending, refetch } = useConsoleQuery(testimonialQueries.list());
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState<TestimonialDraft>(TestimonialForm.blank);
  const [addRefused, setAddRefused] = useState<Record<string, string>>({});
  const [showErrors, setShowErrors] = useState(false);
  const [removing, setRemoving] = useState<ConsoleTestimonial | null>(null);

  const header = <PageHeader title="Testimonials" description="The quotes under “What learners say” on the landing page. Only published ones, with the learner’s permission confirmed, are shown. With none published, the page shows the maker’s note instead." />;
  if (error && !data) return <>{header}<ErrorState message="The testimonials could not be loaded." onRetry={() => void refetch()} /></>;
  if (isPending || !data) return <div aria-busy="true">{header}<CardSkeleton height={220} /></div>;

  const rows = data.testimonials;
  const reload = () => queryClient.invalidateQueries({ queryKey: testimonialQueries.list().queryKey });

  /** Runs one change; a refusal is returned as words, never thrown, so a form can show it where it belongs. */
  const run = async (change: () => Promise<unknown>, done: string): Promise<Record<string, string> | null> => {
    setBusy(true);
    try {
      await change();
      await reload();
      toast.success(done);
      return null;
    } catch (failure) {
      const refused = refusals(failure);
      toast.error(ConsoleFailure.of(failure).lines(LABELS).join(" "));
      return refused;
    } finally {
      setBusy(false);
    }
  };

  const add = async () => {
    setShowErrors(true);
    if (Object.keys(TestimonialForm.problems(adding)).length) return;
    const refused = await run(() => consoleApi.addTestimonial(TestimonialForm.payload(adding)), "Added. It goes last.");
    setAddRefused(refused ?? {});
    if (!refused) {
      setAdding(TestimonialForm.blank());
      setShowErrors(false);
    }
  };

  const move = (id: number, direction: -1 | 1) => {
    const ids = rows.map((row) => row.id);
    const next = TestimonialForm.move(ids, id, direction);
    if (next !== ids) void run(() => consoleApi.reorderTestimonials(next), "Order saved.");
  };

  return (
    <div>
      {header}
      <div className="grid gap-4">
        <section aria-label="Add a testimonial" className="rounded-2xl border bg-card p-[18px] shadow-card">
          <h2 className="font-sans text-base font-extrabold">Add a testimonial</h2>
          <p className="mb-3 text-[13px] font-semibold text-muted-foreground">Only add words a learner has agreed to share. It goes last, and stays hidden until you publish it.</p>
          <TestimonialFields idPrefix="new" draft={adding} onChange={setAdding} problems={showErrors ? TestimonialForm.problems(adding) : {}} refused={addRefused} />
          <div className="mt-3">
            <Button type="button" size="lg" disabled={busy} onClick={() => void add()} className="gap-1.5">
              <PlusIcon aria-hidden="true" /> Add testimonial
            </Button>
          </div>
        </section>

        <section aria-label="Testimonials" className="grid gap-3">
          {rows.length === 0 ? (
            <div className="rounded-2xl border bg-card shadow-card">
              <EmptyState icon={MessageSquareQuoteIcon} title="No testimonials yet" description="The landing page shows the maker’s note until at least one is published." />
            </div>
          ) : (
            rows.map((row, index) => (
              <Row key={row.id} row={row} first={index === 0} last={index === rows.length - 1} busy={busy} run={run} onMove={move} onDelete={() => setRemoving(row)} />
            ))
          )}
        </section>
      </div>

      <ConfirmDialog
        open={!!removing}
        onOpenChange={(open) => !open && setRemoving(null)}
        title="Delete this testimonial?"
        description={removing ? `“${removing.name}” will be removed for good, and from the landing page if it is published. The change log keeps what it said.` : ""}
        confirmLabel="Delete it"
        onConfirm={async () => {
          if (removing) await run(() => consoleApi.deleteTestimonial(removing.id), "Deleted.");
          setRemoving(null);
        }}
      />
    </div>
  );
}

type RowProps = {
  row: ConsoleTestimonial;
  first: boolean;
  last: boolean;
  busy: boolean;
  run: (change: () => Promise<unknown>, done: string) => Promise<Record<string, string> | null>;
  onMove: (id: number, direction: -1 | 1) => void;
  onDelete: () => void;
};

function Row({ row, first, last, busy, run, onMove, onDelete }: RowProps) {
  const [draft, setDraft] = useState<TestimonialDraft | null>(null);
  const [refused, setRefused] = useState<Record<string, string>>({});
  const why = TestimonialForm.cannotPublish(TestimonialForm.from(row), row.is_sample);

  const save = async () => {
    if (!draft) return;
    const problems = TestimonialForm.problems(draft, row.is_sample);
    if (Object.keys(problems).length) return setRefused(problems);
    const changes = TestimonialForm.changes(row, draft);
    if (!Object.keys(changes).length) return setDraft(null);
    const failed = await run(() => consoleApi.updateTestimonial(row.id, changes), "Saved.");
    setRefused(failed ?? {});
    if (!failed) setDraft(null);
  };

  const toggle = async () => {
    const failed = await run(() => consoleApi.updateTestimonial(row.id, { is_published: !row.is_published }), row.is_published ? "Taken off the landing page." : "Published. It shows on the landing page now.");
    setRefused(failed ?? {});
  };

  return (
    <article aria-label={`Testimonial from ${row.name}`} className="rounded-2xl border bg-card p-[18px] shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-extrabold">
            {row.name} <span className="font-semibold text-muted-foreground">· {row.context}</span>
          </p>
          <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] font-extrabold">
            <span className={row.is_published ? "rounded-md bg-success-soft px-1.5 py-px text-success-text" : "rounded-md bg-muted px-1.5 py-px text-muted-foreground"}>{row.is_published ? "Published" : "Not published"}</span>
            {row.is_sample ? <span className="rounded-md bg-marigold-soft px-1.5 py-px text-marigold-text">Sample: never shown</span> : null}
            {!row.consent_confirmed ? <span className="rounded-md bg-destructive-soft px-1.5 py-px text-destructive-text">No permission confirmed</span> : null}
            {row.rating ? <span className="rounded-md bg-muted px-1.5 py-px text-muted-foreground">{row.rating} stars</span> : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Button type="button" variant="outline" size="icon" aria-label={`Move ${row.name} up`} disabled={busy || first} onClick={() => onMove(row.id, -1)}>
            <ArrowUpIcon />
          </Button>
          <Button type="button" variant="outline" size="icon" aria-label={`Move ${row.name} down`} disabled={busy || last} onClick={() => onMove(row.id, 1)}>
            <ArrowDownIcon />
          </Button>
          <Button type="button" variant="outline" size="lg" className="gap-1.5" disabled={busy} onClick={() => void (draft ? setDraft(null) : setDraft(TestimonialForm.from(row)))}>
            <PencilIcon aria-hidden="true" /> {draft ? "Close" : "Edit"}
          </Button>
          <Button type="button" variant={row.is_published ? "outline" : "default"} size="lg" className="gap-1.5" disabled={busy || (!row.is_published && !!why)} onClick={() => void toggle()}>
            {row.is_published ? <EyeOffIcon aria-hidden="true" /> : <EyeIcon aria-hidden="true" />} {row.is_published ? "Unpublish" : "Publish"}
          </Button>
          <Button type="button" variant="destructive" size="icon" aria-label={`Delete ${row.name}`} disabled={busy} onClick={onDelete}>
            <Trash2Icon />
          </Button>
        </div>
      </div>
      <blockquote className="mt-3 text-[15px]">“{row.quote}”</blockquote>
      {!row.is_published && why && !draft ? <p className="mt-2 text-xs font-semibold text-muted-foreground">{why} Use Edit to confirm it.</p> : null}
      {refused.is_published && !draft ? <p role="alert" className="mt-2 text-xs font-bold text-destructive-text">{refused.is_published}</p> : null}
      {draft ? (
        <div className="mt-4 border-t border-border pt-4">
          <TestimonialFields idPrefix={`edit-${row.id}`} draft={draft} onChange={setDraft} problems={{}} refused={refused} isSample={row.is_sample} />
          <div className="mt-3 flex gap-2">
            <Button type="button" size="lg" disabled={busy} onClick={() => void save()}>
              Save changes
            </Button>
            <Button type="button" variant="outline" size="lg" disabled={busy} onClick={() => { setDraft(null); setRefused({}); }}>
              Cancel
            </Button>
          </div>
        </div>
      ) : null}
    </article>
  );
}
