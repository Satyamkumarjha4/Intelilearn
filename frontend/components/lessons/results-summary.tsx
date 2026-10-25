import { QuizResultCard } from "@/components/lessons/quiz-result-card";
import { QuizReview } from "@/components/lessons/quiz-review";
import { QuizNames } from "@/lib/quiz-names";
import type { LessonDetail, QuizKind } from "@/lib/types";

/** The scores of the quizzes already answered (kept after a reload), each with its review. */
export function ResultsSummary({ lesson, skip }: { lesson: LessonDetail; skip?: QuizKind }) {
  const kinds: QuizKind[] = ["diagnostic", "prerequisite"];
  return (
    <>
      {kinds.map((kind) => {
        const result = lesson.results[kind];
        if (!result || kind === skip) return null;
        return (
          <section key={kind} className="flex flex-col gap-3" aria-label={QuizNames.resultLabel(kind)}>
            <QuizResultCard result={result} level={lesson.level} />
            <QuizReview lessonId={lesson.id} kind={kind} />
          </section>
        );
      })}
    </>
  );
}
