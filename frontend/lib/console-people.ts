import { ONBOARDING_COPY } from "@/lib/onboarding-flow";
import { ConsoleFormat } from "@/lib/console-format";
import { RunText } from "@/lib/run-text";
import type { ConsoleLearner, LearnerSummary } from "@/lib/types";

const DAY_MS = 86_400_000;
const NONE = "–";

const labels = (field: keyof typeof ONBOARDING_COPY) => new Map<string, string>(ONBOARDING_COPY[field].map((choice) => [choice.value, choice.label]));
const LEVELS = labels("education_level");
const GOALS = labels("goal");
const LANGUAGES = labels("preferred_language");

/** The words of one row of the Learners page. The choices are named as the learner saw them when they chose (a language in its own script). */
export class LearnerText {
  /** "School · Class 10", "Self-learner", or a dash when nothing was filled in. */
  static studies(learner: Pick<ConsoleLearner, "education_level" | "grade_or_year">): string {
    const level = LEVELS.get(learner.education_level) ?? learner.education_level;
    return [level, LearnerText.stage(learner)].filter(Boolean).join(" · ") || NONE;
  }

  /** What learners type is free text, often just "10" or "4": at school that is a class, at college a year. */
  private static stage({ education_level: level, grade_or_year: value }: Pick<ConsoleLearner, "education_level" | "grade_or_year">): string {
    if (!/^\d{1,2}$/.test(value.trim())) return value.trim();
    if (level === "school") return `Class ${value.trim()}`;
    return level === "undergraduate" || level === "postgraduate" ? `Year ${value.trim()}` : value.trim();
  }

  /** The name, or "No name" for an account that never gave one (the email is on the line below). */
  static displayName(learner: Pick<ConsoleLearner, "name">): string {
    return learner.name.trim() || "No name";
  }

  static goal(learner: Pick<ConsoleLearner, "goal">): string {
    return GOALS.get(learner.goal) ?? (learner.goal || NONE);
  }

  /** The language in its own script; a code that is not known is shown as it is. */
  static language(code: string): string {
    return LANGUAGES.get(code) ?? (code || NONE);
  }

  static lastActive(iso: string | null, now: Date): { text: string; title: string } {
    if (!iso) return { text: "Never", title: "Has not signed in or opened a lesson" };
    return { text: RunText.ago(iso, now), title: RunText.exact(iso) };
  }

  static onboarding(learner: Pick<ConsoleLearner, "profile_complete">): { label: string; tone: "ok" | "off" } {
    return learner.profile_complete ? { label: "Finished", tone: "ok" } : { label: "Not finished", tone: "off" };
  }
}

export type LearnerSample = { rows: readonly ConsoleLearner[]; /** True when there are learners beyond `rows`. */ more: boolean };
export type PeopleTile = { key: string; label: string; value: string; detail: string; small?: boolean };

/** The four tiles of the Learners page. The counts come from the API's summary (everyone, whatever is searched); "new this
 *  week" and "most common" are worked out from a sample of the newest learners, and say so when it is only a sample. */
export class LearnerStats {
  static tiles(summary: LearnerSummary, sample: LearnerSample, now: Date): PeopleTile[] {
    const fresh = LearnerStats.newThisWeek(sample.rows, sample.more, now);
    const common = LearnerStats.mostCommon(sample.rows);
    const joined = fresh.count === 0 ? "None joined this week" : `+${ConsoleFormat.count(fresh.count)}${fresh.atLeast ? " or more" : ""} this week`;
    const commonDetail = !common
      ? "No one has chosen a level yet"
      : sample.more
        ? `${ConsoleFormat.count(common.count)} of the newest ${ConsoleFormat.count(sample.rows.length)}`
        : `${ConsoleFormat.count(common.count)} ${common.count === 1 ? "learner" : "learners"}`;
    return [
      { key: "learners", label: "Learners", value: ConsoleFormat.count(summary.total), detail: joined },
      {
        key: "onboarding",
        label: "Finished onboarding",
        value: summary.total > 0 ? ConsoleFormat.percent(ConsoleFormat.ratio(summary.profile_complete, summary.total)) : NONE,
        detail: summary.total > 0 ? `${ConsoleFormat.count(summary.profile_complete)} of ${ConsoleFormat.count(summary.total)} learners` : "No learners yet",
      },
      { key: "active", label: "Active this week", value: ConsoleFormat.count(summary.active_7d), detail: "Signed in or opened a lesson" },
      { key: "common", label: "Most common", value: common?.label ?? NONE, detail: commonDetail, small: true },
    ];
  }

  /** The level and class most learners share; only those who gave a level count, and a tie goes to the first alphabetically. */
  static mostCommon(rows: readonly Pick<ConsoleLearner, "education_level" | "grade_or_year">[]): { label: string; count: number } | null {
    const counts = new Map<string, number>();
    for (const row of rows) {
      if (!row.education_level) continue;
      const label = LearnerText.studies(row);
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }
    const [best] = [...counts.entries()].sort(([a, x], [b, y]) => y - x || a.localeCompare(b));
    return best ? { label: best[0], count: best[1] } : null;
  }

  /** Learners who joined in the last 7 days. When every known learner is new and there are more, the real number may be higher. */
  static newThisWeek(rows: readonly Pick<ConsoleLearner, "joined_at">[], more: boolean, now: Date): { count: number; atLeast: boolean } {
    const count = rows.filter((row) => now.getTime() - Date.parse(row.joined_at) <= 7 * DAY_MS).length;
    return { count, atLeast: more && count === rows.length && count > 0 };
  }
}

/** The search box of the Learners page, as it lives in the address (`?q=`). */
export class PeopleUrl {
  static search(params: { get(name: string): string | null }): string {
    return params.get("q")?.trim() ?? "";
  }

  /** `""` for nothing to search for, else `?q=aditi+rao`. */
  static searchQuery(text: string): string {
    const q = text.trim();
    return q ? `?${new URLSearchParams({ q })}` : "";
  }
}

/** Links out of the console to the Django admin, where an account can be changed (the console only reads accounts). */
export class AdminLinks {
  /** `base` is the admin's address (`http://host/admin`) or just the backend's origin; null when it is unset or not a web address. */
  static userChange(base: string | undefined, id: string): string | null {
    if (!base) return null;
    let url: URL;
    try {
      url = new URL(base);
    } catch {
      return null;
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    const path = url.pathname.replace(/\/+$/, "") || "/admin";
    return `${url.origin}${path}/accounts/user/${encodeURIComponent(id)}/change/`;
  }
}
