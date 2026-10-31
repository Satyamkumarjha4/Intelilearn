import { ApiError } from "@/lib/api";
import type { MaterialKind, OfferedSheet, QuizResultSummary } from "@/lib/types";

export type SheetInfo = {
  kind: MaterialKind;
  title: string;
  /** One line on what the sheet is. */
  text: string;
  bullets: [string, string, string];
  /** A rough guess at the time it takes, in the words of a card. */
  time: string;
};

const SHEETS: SheetInfo[] = [
  {
    kind: "cheat_sheet",
    title: "Cheat sheet",
    text: "The essentials on one or two pages.",
    bullets: ["Formulas and rules in one place", "Key terms at a glance", "Quick to scan and easy to print"],
    time: "2 min read",
  },
  {
    kind: "revision_sheet",
    title: "Revision sheet",
    text: "Every subtopic, in short notes.",
    bullets: ["Key points for each subtopic", "Worked examples to follow", "Common mistakes to avoid"],
    time: "10 min read",
  },
  {
    kind: "practice_sheet",
    title: "Practice sheet",
    text: "Questions from easy to hard.",
    bullets: ["15 to 25 questions to try", "Check your answers as you go", "Solutions when you want them"],
    time: "20 min to work through",
  },
];

/** The three study sheets, described once for the choice screen and the Study sheets tab alike. */
export class SheetCatalog {
  /** In the order a learner reads them. */
  static all(): SheetInfo[] {
    return SHEETS;
  }

  static of(kind: MaterialKind): SheetInfo {
    return SHEETS.find((sheet) => sheet.kind === kind)!;
  }

  /** "cheat sheet", for use in a sentence. */
  static noun(kind: MaterialKind): string {
    return SheetCatalog.of(kind).title.toLowerCase();
  }

  /** The choice screen's button follows the card picked. */
  static makeLabel(kind: MaterialKind): string {
    return `Make my ${SheetCatalog.noun(kind)}`;
  }

  /** The dashed tab that asks for a sheet the lesson does not have yet. */
  static addLabel(kind: MaterialKind): string {
    return `Add ${SheetCatalog.noun(kind)}`;
  }
}

export type SheetTabState = "ready" | "building" | "missing";
export type SheetTab = { kind: MaterialKind; title: string; state: SheetTabState };

/** What can be asked for now: the two sheets of the spec. A practice sheet that exists is still opened and shown. */
const OFFERED: readonly OfferedSheet[] = ["cheat_sheet", "revision_sheet"];

/** The row of tabs above a lesson's sheets. */
export class SheetTabs {
  /**
   * The sheets the lesson has, then the ones it lacks and can be asked for. The API lists `have` in its own order, so
   * the order here comes from the catalogue. `building` is the sheets being written right now, if the page knows which.
   */
  static of(have: MaterialKind[], building: MaterialKind[]): SheetTab[] {
    const state = (kind: MaterialKind): SheetTabState => (have.includes(kind) ? "ready" : building.includes(kind) ? "building" : "missing");
    const tabs = SHEETS.map(({ kind, title }) => ({ kind, title, state: state(kind) }));
    const shown = tabs.filter((tab) => tab.state !== "missing" || (OFFERED as readonly MaterialKind[]).includes(tab.kind));
    return [...shown.filter((tab) => tab.state === "ready"), ...shown.filter((tab) => tab.state !== "ready")];
  }

  /** The tab to show open: the one asked for if it exists or is being written, else the first sheet there is. */
  static pick(tabs: SheetTab[], wanted: MaterialKind | null): MaterialKind | null {
    const open = tabs.find((tab) => tab.kind === wanted && tab.state !== "missing");
    return open?.kind ?? tabs.find((tab) => tab.state === "ready")?.kind ?? null;
  }
}

/** Asking for sheets from a lesson: which can still be asked for, and what a refusal because they exist says. */
export class SheetRequests {
  /** The sheets the lesson lacks that can be asked for, in the order they are written. */
  static missing(have: MaterialKind[]): OfferedSheet[] {
    return OFFERED.filter((kind) => !have.includes(kind));
  }

  /** Both together are for a lesson that has neither (a request that names one that exists is refused). */
  static canAskForBoth(have: MaterialKind[]): boolean {
    return SheetRequests.missing(have).length === OFFERED.length;
  }

  static one(kind: OfferedSheet): OfferedSheet[] {
    return [kind];
  }

  static pair(): OfferedSheet[] {
    return [...OFFERED];
  }

  static bothLabel(): string {
    return "Add both sheets";
  }

  /** The sheets an `already_exists` answer says are there; none for any other error. */
  static existing(error: unknown): MaterialKind[] {
    if (!(error instanceof ApiError) || error.code !== "already_exists") return [];
    const kinds = error.extra.kinds;
    if (!Array.isArray(kinds)) return [];
    return SHEETS.map((sheet) => sheet.kind).filter((kind) => kinds.includes(kind));
  }
}

/** The celebration above the choice of sheets. */
export class MasteryBanner {
  static of(result: Pick<QuizResultSummary, "correct" | "total"> | null): { headline: string; text: string } {
    const text = "No need for a full lesson. Pick a sheet to keep it sharp.";
    if (!result) return { headline: "You already know this!", text };
    const score = `${result.correct} out of ${result.total}.`;
    return { headline: result.correct >= result.total ? `${score} You already know this!` : `${score} You already know this well!`, text };
  }
}
