import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { StageView } from "@/lib/stage-view";
import type { Band, QuizResultSummary } from "@/lib/types";

const BAND_LABELS: Record<Band, string> = {
  basic: "Basics",
  easy_moderate: "Easy applications",
  moderate: "Standard problems",
  moderate_hard: "Edge cases",
  hard: "Expert",
};

/** The score right after a quiz, by band, and what happens next. */
export function QuizResultCard({ result, level }: { result: QuizResultSummary; level?: string }) {
  const bands = StageView.bandsOf(result);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl">
          <h2>
            {result.correct} of {result.total} correct
          </h2>
        </CardTitle>
        <CardDescription>
          {StageView.nextStep(result.route, level)}
          {result.dont_know > 0 && ` You said “I don't know” ${result.dont_know} time${result.dont_know === 1 ? "" : "s"}, which is exactly what helps.`}
        </CardDescription>
      </CardHeader>
      {bands.length > 0 && (
        <CardContent className="flex flex-col gap-2">
          {bands.map(([band, [right, total]]) => (
            <div key={band} className="grid grid-cols-[10rem_1fr_3rem] items-center gap-3 text-sm">
              <span>{BAND_LABELS[band]}</span>
              <Progress value={total ? right / total : 0} label={`${BAND_LABELS[band]}: ${right} of ${total}`} />
              <span className="text-right text-muted-foreground">
                {right}/{total}
              </span>
            </div>
          ))}
        </CardContent>
      )}
    </Card>
  );
}
