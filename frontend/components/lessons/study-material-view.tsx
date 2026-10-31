"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { CheatSheetView } from "@/components/lessons/cheat-sheet-view";
import { PipelineProgress } from "@/components/lessons/pipeline-progress";
import { PracticeSheetView } from "@/components/lessons/practice-sheet-view";
import { RevisionSheetView } from "@/components/lessons/revision-sheet-view";
import { SheetTabRow } from "@/components/lessons/sheet-tab-row";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { ActionRefusedMessage } from "@/lib/action-refused";
import { lessonsApi } from "@/lib/lessons-api";
import type { PipelineModel } from "@/lib/pipeline";
import { SheetCatalog, SheetRequests, SheetTabs } from "@/lib/study-sheets";
import type { CheatSheet, LessonDetail, MaterialKind, OfferedSheet, PracticeSheet, RevisionSheet, Solution, StudyMaterial } from "@/lib/types";

type Props = {
  lesson: LessonDetail;
  pipeline: PipelineModel;
  /** The lesson should be read again: a sheet was asked for, so it now has a run. */
  onRequested: () => void | Promise<void>;
};
type Sheet = CheatSheet | RevisionSheet | PracticeSheet;
type Loaded = Partial<Record<MaterialKind, StudyMaterial<Sheet>>>;

/**
 * The Study sheets tab of any ready lesson: a row of tabs (a chunky one per sheet, a dashed "+ Add" one for each sheet
 * still missing, and one for both when it has neither), the PDF, and the open sheet. Asking for sheets turns their tabs
 * into the building screen, inline, and the first one opens when it lands. A sheet that already exists (the server says
 * so with a 409) is simply opened. Fixed templates, no generated code. A sheet stays mounted once opened, so a practice
 * sheet keeps its answers while the learner looks at another.
 */
export function StudyMaterialView({ lesson, pipeline, onRequested }: Props) {
  const have = lesson.materials;
  const writing = lesson.active_run_id !== null;
  // The page is told only that a run is active, not which sheets it writes, so the ones asked for are remembered here.
  const [requested, setRequested] = useState<MaterialKind[]>([]);
  const [wanted, setWanted] = useState<MaterialKind | null>(null);
  const [starting, setStarting] = useState(false);
  const [loaded, setLoaded] = useState<Loaded>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [solutions, setSolutions] = useState<Record<string, Solution>>({});

  const unfinished = requested.filter((kind) => !have.includes(kind));
  const pending = writing ? unfinished : [];
  const failed = !writing && unfinished.length > 0 ? unfinished : null;
  const tabs = SheetTabs.of(have, pending);
  const open = SheetTabs.pick(tabs, wanted);
  const openTab = tabs.find((tab) => tab.kind === open);

  useEffect(() => {
    if (!open || openTab?.state !== "ready" || loaded[open]) return;
    let active = true;
    lessonsApi
      .material<Sheet>(lesson.id, open)
      .then((data) => {
        if (!active) return;
        setLoaded((current) => ({ ...current, [open]: data }));
        setLoadError(null);
      })
      .catch((err) => active && setLoadError(err instanceof ApiError ? err.message : "Could not load the sheet."));
    return () => {
      active = false;
    };
  }, [lesson.id, open, openTab?.state, loaded]);

  const request = async (kinds: OfferedSheet[]) => {
    setStarting(true);
    try {
      await lessonsApi.requestMaterial(lesson.id, kinds);
      await onRequested();
      setRequested(kinds);
      setWanted(kinds[0]);
    } catch (err) {
      const existing = SheetRequests.existing(err);
      if (existing.length > 0) {
        // It was made already (another tab, or a moment ago): open it rather than make it again.
        await onRequested();
        setWanted(existing[0]);
      } else {
        toast.error(ActionRefusedMessage.of(err) ?? (err instanceof ApiError ? err.message : "Could not start that sheet."));
      }
    } finally {
      setStarting(false);
    }
  };

  const pdf = async () => {
    const material = open ? loaded[open] : undefined;
    if (!open || !material) return;
    try {
      const { StudyPdf } = await import("@/lib/pdf/study-pdf");
      const blob = await StudyPdf.blob(open, material.content, solutions);
      const url = URL.createObjectURL(blob);
      Object.assign(document.createElement("a"), { href: url, download: `${open}.pdf` }).click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Could not make the PDF.");
    }
  };

  const remember = (found: Record<string, Solution>) => setSolutions((current) => ({ ...current, ...found }));

  return (
    <div className="flex flex-col gap-5">
      <SheetTabRow
        tabs={tabs}
        selected={open}
        locked={writing || starting}
        canExport={Boolean(open && loaded[open])}
        canAskForBoth={SheetRequests.canAskForBoth(have)}
        onSelect={setWanted}
        onAdd={request}
        onPdf={pdf}
      />

      {failed && (
        <Alert variant="destructive">
          <AlertDescription className="flex flex-wrap items-center gap-3">
            We couldn&apos;t write your {failed.map((kind) => SheetCatalog.noun(kind)).join(" and your ")} this time.
            <Button size="sm" variant="outline" disabled={starting} onClick={() => request(failed.filter((kind): kind is OfferedSheet => kind !== "practice_sheet"))}>
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {writing && pending.length === 0 && <PipelineProgress pipeline={pipeline} title="Writing more study sheets" />}
      {pending.length > 0 && (!open || pending.includes(open)) && (
        <PipelineProgress pipeline={pipeline} title={`Writing your ${pending.map((kind) => SheetCatalog.noun(kind)).join(" and your ")}`} />
      )}

      {!open && !writing && !failed && (
        <Alert>
          <AlertDescription>No study sheets yet. Pick one above and we&apos;ll write it from this lesson.</AlertDescription>
        </Alert>
      )}

      {loadError && openTab?.state === "ready" && !loaded[open!] && (
        <Alert variant="destructive">
          <AlertDescription>{loadError}</AlertDescription>
        </Alert>
      )}
      {open && openTab?.state === "ready" && !loaded[open] && !loadError && <Skeleton className="h-64 rounded-[22px]" aria-busy="true" />}

      {SheetCatalog.all().map(({ kind }) => {
        const material = loaded[kind];
        if (!material || !have.includes(kind)) return null;
        return (
          <div key={kind} hidden={kind !== open}>
            {kind === "cheat_sheet" && <CheatSheetView sheet={material.content as CheatSheet} />}
            {kind === "revision_sheet" && <RevisionSheetView sheet={material.content as RevisionSheet} />}
            {kind === "practice_sheet" && <PracticeSheetView lessonId={lesson.id} sheet={material.content as PracticeSheet} onSolutions={remember} />}
          </div>
        );
      })}
    </div>
  );
}
