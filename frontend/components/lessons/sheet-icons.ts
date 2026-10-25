import { BookOpenCheckIcon, PencilLineIcon, ScrollTextIcon, type LucideIcon } from "lucide-react";

import type { MaterialKind } from "@/lib/types";

/** One icon per kind of study sheet, shared by the choice cards and the tab row. */
export const SHEET_ICONS: Record<MaterialKind, LucideIcon> = {
  cheat_sheet: ScrollTextIcon,
  revision_sheet: BookOpenCheckIcon,
  practice_sheet: PencilLineIcon,
};
