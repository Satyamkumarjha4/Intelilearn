"use client";

import { DownloadIcon, PrinterIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { CheatSheetView } from "@/components/lessons/cheat-sheet-view";
import { MATERIAL_OPTIONS } from "@/components/lessons/mastery-choice";
import { PipelineProgress } from "@/components/lessons/pipeline-progress";
import { PracticeSheetView } from "@/components/lessons/practice-sheet-view";
import { RevisionSheetView } from "@/components/lessons/revision-sheet-view";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api";
import { lessonsApi } from "@/lib/lessons-api";
import type { PipelineModel } from "@/lib/pipeline";
import type { CheatSheet, LessonDetail, MaterialKind, PracticeSheet, RevisionSheet, Solution, StudyMaterial } from "@/lib/types";

type Props = { lesson: LessonDetail; pipeline: PipelineModel; onRequested: () => void };
type Sheet = CheatSheet | RevisionSheet | PracticeSheet;

const LABELS = Object.fromEntries(MATERIAL_OPTIONS.map((o) => [o.kind, o.title])) as Record<MaterialKind, string>;

function Sheets({ lessonId, kind, solutions, setSolutions }: {
  lessonId: string; kind: MaterialKind; solutions: Record<string, Solution>; setSolutions: (s: Record<string, Solution>) => void;
}) {
  const [material, setMaterial] = useState<StudyMaterial<Sheet> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    lessonsApi
      .material<Sheet>(lessonId, kind)
      .then((data) => active && setMaterial(data))
      .catch((err) => active && setError(err instanceof ApiError ? err.message : "Could not load the sheet."));
    return () => {
      active = false;
    };
  }, [lessonId, kind]);

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }
  if (!material) return <div className="h-40" aria-busy="true" />;

  const download = async () => {
    try {
      const { StudyPdf } = await import("@/lib/pdf/study-pdf");
      const blob = await StudyPdf.blob(kind, material.content, solutions);
      const url = URL.createObjectURL(blob);
      const link = Object.assign(document.createElement("a"), { href: url, download: `${kind}.pdf` });
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Could not make the PDF.");
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-2 print:hidden">
        <Button variant="outline" size="sm" onClick={download}>
          <DownloadIcon /> Download PDF
        </Button>
        <Button variant="outline" size="sm" onClick={() => window.print()}>
          <PrinterIcon /> Print
        </Button>
      </div>
      {kind === "cheat_sheet" && <CheatSheetView sheet={material.content as CheatSheet} />}
      {kind === "revision_sheet" && <RevisionSheetView sheet={material.content as RevisionSheet} />}
      {kind === "practice_sheet" && (
        <PracticeSheetView lessonId={lessonId} sheet={material.content as PracticeSheet} onSolutions={(s) => setSolutions({ ...solutions, ...s })} />
      )}
    </div>
  );
}

/** The sheets of a mastery lesson in tabs, with a way to ask for the others. Fixed templates, no generated code. */
export function StudyMaterialView({ lesson, pipeline, onRequested }: Props) {
  const [solutions, setSolutions] = useState<Record<string, Solution>>({});
  const [busy, setBusy] = useState<MaterialKind | null>(null);
  const have = lesson.materials;
  const missing = MATERIAL_OPTIONS.filter((o) => !have.includes(o.kind));
  const writing = lesson.active_run_id !== null;

  const request = async (kind: MaterialKind) => {
    setBusy(kind);
    try {
      await lessonsApi.requestMaterial(lesson.id, kind);
      onRequested();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not start that sheet.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      {have.length > 0 && (
        <Tabs defaultValue={have[0]} key={have.join()}>
          <TabsList className="print:hidden">
            {have.map((kind) => (
              <TabsTrigger key={kind} value={kind}>
                {LABELS[kind]}
              </TabsTrigger>
            ))}
          </TabsList>
          {have.map((kind) => (
            <TabsContent key={kind} value={kind}>
              <Sheets lessonId={lesson.id} kind={kind} solutions={solutions} setSolutions={setSolutions} />
            </TabsContent>
          ))}
        </Tabs>
      )}

      {writing && <PipelineProgress pipeline={pipeline} title="Writing another study sheet" />}

      {!writing && missing.length > 0 && (
        <section className="flex flex-col gap-2 print:hidden" aria-label="Get another sheet">
          <h2 className="text-lg font-medium">Get another sheet</h2>
          <div className="flex flex-wrap gap-2">
            {missing.map(({ kind, title }) => (
              <Button key={kind} variant="outline" disabled={busy !== null} onClick={() => request(kind)}>
                {busy === kind ? "Starting…" : title}
              </Button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
