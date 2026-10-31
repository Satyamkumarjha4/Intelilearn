import type { LessonDetail } from "@/lib/types";

export type FollowupLink = { label: string; title: string; href: string };

export type FollowupLinksView = {
  /** "Made from: <the lesson>" on a lesson that is a follow-up and whose parent still exists. */
  madeFrom: FollowupLink | null;
  /** Its Foundation and Advanced lessons on a lesson that has them, Foundation first. */
  followups: FollowupLink[];
};

const LABELS = { foundation: "Foundation lesson", advanced: "Advanced lesson" } as const;

/** The links between a lesson and the lessons made from it, both ways, for the lesson page. */
export class FollowupLinks {
  static of(lesson: Pick<LessonDetail, "followup_of" | "followups">): FollowupLinksView {
    const parent = lesson.followup_of;
    const made = Object.entries(LABELS).flatMap(([level, label]) => {
      const child = lesson.followups[level as keyof typeof LABELS];
      return child ? [{ label, title: child.title, href: FollowupLinks.href(child.id) }] : [];
    });
    return {
      madeFrom: parent ? { label: "Made from", title: parent.title, href: FollowupLinks.href(parent.id) } : null,
      followups: made,
    };
  }

  /** Whether there is anything to show. */
  static any(view: FollowupLinksView): boolean {
    return view.madeFrom !== null || view.followups.length > 0;
  }

  static href(lessonId: string): string {
    return `/lessons/${lessonId}`;
  }
}
