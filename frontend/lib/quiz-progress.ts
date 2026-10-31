import type { NodeStatus } from "@/lib/types";

export type ProgressState = "done" | "active" | "waiting";
export type ProgressStep = { label: string; state: ProgressState };

type Group = { label: string; nodes: readonly string[]; last: string };

/** The steps of making a quiz, in the words a learner uses, worked out from which graph steps have run. */
export class QuizProgress {
  private static readonly GROUPS: readonly Group[] = [
    {
      label: "Finding your level",
      nodes: ["level_from_rating", "level_from_scores", "generate_pool", "validate_pool", "publish_calibration", "await_calibration", "level_from_walk"],
      last: "level_from_walk",
    },
    { label: "Planning your questions", nodes: ["plan_quiz", "plan_batches"], last: "plan_batches" },
    { label: "Writing your questions", nodes: ["generate_questions", "questions_join"], last: "questions_join" },
    { label: "Getting everything ready", nodes: ["persist_attempt"], last: "persist_attempt" },
  ];

  /**
   * A step is done once a later step has begun, and the last step is done when it has finished; the first one that has
   * begun and is not done is the active one; at the start, before anything has run, the first is active. A retake knows
   * the level already, so a quiz that went straight to planning has no "Finding your level" step.
   */
  static steps(nodeStatus: Record<string, NodeStatus>): ProgressStep[] {
    const [level, ...rest] = QuizProgress.GROUPS;
    const skipsLevel = !QuizProgress.began(nodeStatus, level) && rest.some((group) => QuizProgress.began(nodeStatus, group));
    const groups = skipsLevel ? rest : QuizProgress.GROUPS;
    const began = groups.map((group) => QuizProgress.began(nodeStatus, group));
    const current = Math.max(began.lastIndexOf(true), 0);
    return groups.map((group, index) => {
      const finished = index === groups.length - 1 && nodeStatus[group.last] === "done";
      const state: ProgressState = index < current || finished ? "done" : index === current ? "active" : "waiting";
      return { label: group.label, state };
    });
  }

  private static began(nodeStatus: Record<string, NodeStatus>, group: Group): boolean {
    return group.nodes.some((node) => node in nodeStatus);
  }
}
