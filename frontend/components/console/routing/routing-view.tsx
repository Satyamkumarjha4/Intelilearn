"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/console/error-state";
import { SelectBox } from "@/components/console/field-row";
import { PageHeader } from "@/components/console/page-header";
import { SaveBar } from "@/components/console/save-bar";
import { CardSkeleton } from "@/components/console/skeletons";
import { UnsavedChangesGuard } from "@/components/console/unsaved-guard";
import { useConsoleQuery } from "@/components/console/use-console-query";
import { NodeEditor } from "@/components/console/routing/node-editor";
import { NodeList } from "@/components/console/routing/node-list";
import { ProfileDialog } from "@/components/console/routing/profile-dialog";
import { useRoutingEdits } from "@/components/console/routing/use-routing-edits";
import { Card } from "@/components/ui/card";
import { consoleApi } from "@/lib/console-api";
import { ConsoleFailure } from "@/lib/console-failure";
import { consoleQueries } from "@/lib/console-queries";
import { RoutingDraft } from "@/lib/routing-draft";
import { RoutingView as View } from "@/lib/routing-view";
import type { ProfilePreview } from "@/lib/types";

/** Where the editor moves from under the list to beside it. */
const WIDE = "(min-width: 1180px)";

/** The Model routing page. Edits are local until "Save routing"; the selected step lives in the address (`?node=`). */
export function RoutingView() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const routing = useConsoleQuery(consoleQueries.routing());
  const profiles = useConsoleQuery(consoleQueries.profiles());
  const models = useConsoleQuery(consoleQueries.models());
  const edits = useRoutingEdits(routing.data);
  const [preview, setPreview] = useState<ProfilePreview | null>(null);
  const [profileChoice, setProfileChoice] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const editorRef = useRef<HTMLDivElement>(null);

  const choose = async (name: string) => {
    setProfileChoice(name);
    if (!name) return;
    setPreviewing(true);
    try {
      setPreview(await consoleApi.previewProfile(name));
    } catch (error) {
      toast.error(ConsoleFailure.of(error).message);
    } finally {
      setPreviewing(false);
      setProfileChoice("");
    }
  };

  const header = (
    <PageHeader
      title="Model routing"
      description="Which model handles each step, and what to fall back to. Changes apply to lessons started after you save."
      actions={
        profiles.data?.length ? (
          <label className="inline-flex items-center gap-2 text-[13px] font-bold">
            Apply a profile
            <SelectBox
              id="routing-profile"
              className="w-44"
              value={profileChoice}
              disabled={previewing}
              onChange={(name) => void choose(name)}
              options={[{ value: "", label: previewing ? "Loading…" : "Choose…" }, ...profiles.data.map((profile) => ({ value: profile.name, label: profile.label }))]}
            />
          </label>
        ) : null
      }
    />
  );

  if (routing.error && !routing.data) return <>{header}<ErrorState message="The routing could not be loaded." onRetry={() => void routing.refetch()} /></>;
  if (!routing.data) {
    return (
      <div aria-busy="true">
        {header}
        <div className="grid gap-4 min-[1180px]:grid-cols-[minmax(0,1fr)_420px]"><CardSkeleton height={420} /><CardSkeleton height={420} /></div>
      </div>
    );
  }

  const keys = edits.saved.map((node) => node.key);
  const selectedKey = View.selected(params, keys) ?? keys[0] ?? null;
  const selected = selectedKey ? edits.current.get(selectedKey) : undefined;
  const select = (key: string) => {
    router.replace(View.href(pathname, key), { scroll: false });
    if (!window.matchMedia(WIDE).matches) requestAnimationFrame(() => editorRef.current?.scrollIntoView({ block: "start" }));
  };
  const apply = () => {
    if (!preview) return;
    const { applied, skipped } = edits.load(preview);
    setPreview(null);
    toast.success(
      `${preview.label} loaded into ${applied} ${applied === 1 ? "step" : "steps"}${skipped ? `, ${skipped} skipped` : ""}. Review it, then save.`,
    );
  };
  const changed = new Set(edits.changed);

  return (
    <div>
      {header}
      <div className="grid items-start gap-4 min-[1180px]:grid-cols-[minmax(0,1fr)_420px]">
        <Card className="min-w-0 gap-0 p-0">
          <NodeList
            phases={routing.data.phases}
            current={edits.current}
            selected={selectedKey}
            changed={changed}
            failed={new Set(Object.keys(edits.failures))}
            onSelect={select}
          />
        </Card>
        <div ref={editorRef} className="min-w-0 scroll-mt-4 min-[1180px]:sticky min-[1180px]:top-4 min-[1180px]:max-h-[calc(100vh-2rem)] min-[1180px]:overflow-y-auto">
          <Card className="gap-0 p-0" aria-label="Step editor">
            {selected ? (
              <NodeEditor
                key={selected.key}
                node={selected}
                models={models.data ?? []}
                failures={edits.failures[selected.key] ?? []}
                onChange={edits.edit}
              />
            ) : (
              <p className="p-6 text-center text-sm text-muted-foreground">Pick a step to see its models.</p>
            )}
          </Card>
        </div>
      </div>

      <SaveBar
        visible={edits.changed.length > 0}
        summary={RoutingDraft.summary(edits.changed)}
        saveLabel="Save routing"
        saving={edits.saving}
        onDiscard={edits.discard}
        onSave={() => void edits.save()}
      />
      <UnsavedChangesGuard dirty={edits.changed.length > 0} />
      <ProfileDialog preview={preview} editedKeys={changed} onApply={apply} onClose={() => setPreview(null)} />
    </div>
  );
}
