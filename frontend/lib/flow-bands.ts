import type { RoutingThresholds } from "@/lib/types";

export type BandSettings = {
  diagnostic_questions_per_band: number;
  prereq_trigger_max_correct: number;
  mastery_requires_all_correct: boolean;
  prerequisite_question_count: number;
};
export type Zone = "foundations" | "lesson" | "study";
export type BandCell = { score: number; zone: Zone };
export type BandLegend = { zone: Zone; range: string; text: string };
export type BandView = {
  total: number;
  foundationsMax: number;
  masteryMin: number;
  cells: BandCell[];
  legend: BandLegend[];
  notice: string | null;
};

/**
 * Where each quick-check score sends a learner, from the lesson settings. It follows `RoutingPolicy` on the server
 * (`graph/grading.py`): mastery is checked first, then the foundations cut-off, and everything else is the lesson.
 */
export class FlowBands {
  /** Difficulty levels in the quick check; the settings give the questions at each. */
  static readonly LEVELS = 5;

  static thresholds(settings: BandSettings): RoutingThresholds {
    const total = settings.diagnostic_questions_per_band * FlowBands.LEVELS;
    return {
      questions_total: total,
      foundations_max: settings.prereq_trigger_max_correct,
      mastery_min: settings.mastery_requires_all_correct ? total : total - 1,
    };
  }

  static of(settings: BandSettings): BandView {
    const { questions_total: total, foundations_max: foundationsMax, mastery_min: masteryMin } = FlowBands.thresholds(settings);
    const cells = Array.from({ length: total + 1 }, (_, score) => ({ score, zone: FlowBands.zone(score, foundationsMax, masteryMin) }));
    const scores = (zone: Zone) => cells.filter((cell) => cell.zone === zone).map((cell) => cell.score);

    const legend: BandLegend[] = [];
    const texts: Record<Zone, string> = {
      foundations: `Foundations check (${settings.prerequisite_question_count} questions), then a lesson that starts with the basics`,
      lesson: "Lesson at their level",
      study: settings.mastery_requires_all_correct ? "Study sheets, no lesson" : "Study sheets, no lesson (the hardest questions must all be right)",
    };
    for (const zone of ["foundations", "lesson", "study"] as const) {
      const found = scores(zone);
      if (found.length) legend.push({ zone, range: FlowBands.range(found[0], found[found.length - 1]), text: texts[zone] });
    }
    const notice = scores("lesson").length ? null : "With these settings no score gets the regular lesson.";
    return { total, foundationsMax, masteryMin, cells, legend, notice };
  }

  private static zone(score: number, foundationsMax: number, masteryMin: number): Zone {
    if (score >= masteryMin) return "study";
    return score <= foundationsMax ? "foundations" : "lesson";
  }

  private static range(from: number, to: number): string {
    return from === to ? String(from) : `${from}–${to}`;
  }
}
