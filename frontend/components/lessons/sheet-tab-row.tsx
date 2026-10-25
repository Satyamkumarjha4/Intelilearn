"use client";

import { DownloadIcon, Loader2Icon, PlusIcon, PrinterIcon } from "lucide-react";

import { SHEET_ICONS } from "@/components/lessons/sheet-icons";
import { Button } from "@/components/ui/button";
import { SheetCatalog, type SheetTab } from "@/lib/study-sheets";
import type { MaterialKind } from "@/lib/types";

type Props = {
  tabs: SheetTab[];
  selected: MaterialKind | null;
  /** The dashed "add" tabs wait while another sheet is being asked for or written. */
  locked: boolean;
  /** The PDF waits for the open sheet to load. */
  canExport: boolean;
  onSelect: (kind: MaterialKind) => void;
  onAdd: (kind: MaterialKind) => void;
  onPdf: () => void;
};

/** One chunky tab per sheet the lesson has, a dashed "+ Add" tab for each it lacks, and the PDF on the right. */
export function SheetTabRow({ tabs, selected, locked, canExport, onSelect, onAdd, onPdf }: Props) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
      <div role="group" aria-label="Your study sheets" className="flex flex-wrap gap-2.5 pb-1">
        {tabs.map((tab) => {
          const Icon = SHEET_ICONS[tab.kind];
          if (tab.state === "missing") {
            return (
              <Button
                key={tab.kind}
                variant="outline"
                className="h-9 border-dashed px-3 text-muted-foreground shadow-none"
                disabled={locked}
                onClick={() => onAdd(tab.kind)}
              >
                <PlusIcon aria-hidden="true" /> {SheetCatalog.addLabel(tab.kind)}
              </Button>
            );
          }
          return (
            <Button
              key={tab.kind}
              variant={tab.kind === selected ? "default" : "outline"}
              className="h-9 px-3"
              aria-pressed={tab.kind === selected}
              onClick={() => onSelect(tab.kind)}
            >
              {tab.state === "building" ? <Loader2Icon className="motion-safe:animate-spin" aria-hidden="true" /> : <Icon aria-hidden="true" />}
              {tab.title}
              {tab.state === "building" && <span className="sr-only"> (being written)</span>}
            </Button>
          );
        })}
      </div>
      <div className="flex items-center gap-2">
        <Button variant="outline" className="h-9 px-3" disabled={!canExport} onClick={onPdf}>
          <DownloadIcon aria-hidden="true" /> PDF
        </Button>
        <Button variant="ghost" size="icon-lg" aria-label="Print this sheet" disabled={!canExport} onClick={() => window.print()}>
          <PrinterIcon />
        </Button>
      </div>
    </div>
  );
}
