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
import { lessonsApi } from "@/lib/lessons-api";
import type { PipelineModel } from "@/lib/pipeline";
import { SheetCatalog, SheetTabs } from "@/lib/study-sheets";
import type { CheatSheet, LessonDetail, MaterialKind, PracticeSheet, RevisionSheet, Solution, StudyMaterial } from "@/lib/types";

type Props = {
  lesson: LessonDetail;
  pipeline: PipelineModel;
  /** The lesson should be read again: a sheet was asked for, so it now has a run. */
  onRequested: () => void | Promise<void>;
};
type Sheet = CheatSheet | RevisionSheet | PracticeSheet;
type Loaded = Partial<Record<MaterialKind, StudyMaterial<Sheet>>>;

/**
 * The Study sheets tab of a mastery lesson: a row of tabs (a chunky one per sheet, a dashed "+ Add" one for each sheet
 * still missing), the PDF, and the open sheet. Asking for a sheet turns its tab into the building screen, inline, and
 * the sheet opens when it lands. Fixed templates, no generated code. A sheet stays mounted once opened, so a practice
 * sheet keeps its answers while the learner looks at another.
 */
export function StudyMaterialView({ lesson, pipeline, onRequested }: Props) {
  const have = lesson.materials;
  const writing = lesson.active_run_id !== null;
  // The page is told only that a run is active, not which sheet it writes, so the one asked for is remembered here.
  const [requested, setRequested] = useState<MaterialKind | null>(null);
  const [wanted, setWanted] = useState<MaterialKind | null>(null);
  const [starting, setStarting] = useState(false);
  const [loaded, setLoaded] = useState<Loaded>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [solutions, setSolutions] = useState<Record<string, Solution>>({});

  const pending = writing && requested && !have.includes(requested) ? requested : null;
  const failed = !writing && requested && !have.includes(requested) ? requested : null;
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

  const request = async (kind: MaterialKind) => {
    setStarting(true);
    try {
      await lessonsApi.requestMaterial(lesson.id, kind);
      await onRequested();
      setRequested(kind);
      setWanted(kind);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not start that sheet.");
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
        onSelect={setWanted}
        onAdd={request}
        onPdf={pdf}
      />

      {failed && (
        <Alert variant="destructive">
          <AlertDescription className="flex flex-wrap items-center gap-3">
            We couldn&apos;t write your {SheetCatalog.noun(failed)} this time.
            <Button size="sm" variant="outline" disabled={starting} onClick={() => request(failed)}>
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {writing && !pending && <PipelineProgress pipeline={pipeline} title="Writing another study sheet" />}
      {pending && open === pending && <PipelineProgress pipeline={pipeline} title={`Writing your ${SheetCatalog.noun(pending)}`} />}

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
