import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { TestResultView, type Tone } from "@/lib/test-session";
import type { QuestionResult, TestSubmission } from "@/lib/types";

const BADGE: Record<Tone, "success" | "secondary" | "destructive" | "outline"> = {
  full: "success",
  partial: "secondary",
  none: "destructive",
  pending: "outline",
};

/** What a learner may read about the right answer after submitting (the fields the API returns as `solution`). */
function Solution({ row }: { row: QuestionResult }) {
  const s = row.solution as { model_answer?: string; key_points?: string[]; rubric?: string[]; reference_solution?: string };
  if (!s.model_answer && !s.key_points && !s.rubric && !s.reference_solution) return null;
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-muted-foreground">Show the model answer</summary>
      <div className="mt-2 flex flex-col gap-2">
        {s.model_answer && <p>{s.model_answer}</p>}
        {s.key_points && (
          <ul className="list-disc pl-5">
            {s.key_points.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        )}
        {s.rubric && (
          <ul className="list-disc pl-5">
            {s.rubric.map((criterion) => (
              <li key={criterion}>{criterion}</li>
            ))}
          </ul>
        )}
        {s.reference_solution && <pre className="overflow-auto rounded-lg bg-muted/40 p-2 text-xs">{s.reference_solution}</pre>}
      </div>
    </details>
  );
}

/** The result of the lesson test, shown next to the lesson: score, topics to revisit, and each question's feedback. */
export function TestResultPanel({ submission }: { submission: TestSubmission }) {
  const card = submission.result;
  const grading = submission.status === "grading";
  return (
    <Card aria-label="Test result">
      <CardHeader>
        <CardTitle>Your test result</CardTitle>
        <CardDescription aria-live="polite">
          {grading ? "Grading your written answers…" : submission.status === "failed" ? "Grading stopped" : "Graded"}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {submission.status === "failed" && (
          <Alert variant="destructive">
            <AlertTitle>Your written answers could not be graded</AlertTitle>
            <AlertDescription>
              {submission.error || "Something went wrong."} Submit the test again to have them graded. What was marked automatically is shown below.
            </AlertDescription>
          </Alert>
        )}
        {card && (
          <>
            <div className="flex flex-col gap-2">
              <p className="text-lg font-medium">{TestResultView.summary(card)}</p>
              <Progress value={card.score.percent / 100} label="Score" />
            </div>
            {card.topics_to_revisit.length > 0 && (
              <p className="text-sm">
                <span className="font-medium">Worth revisiting:</span> {TestResultView.topics(card)}
              </p>
            )}
            <ol className="flex flex-col gap-3">
              {card.questions.map((row, index) => (
                <li key={row.id} className="flex flex-col gap-1 rounded-lg border p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">Question {index + 1}</span>
                    <span className="text-sm text-muted-foreground">{row.concept}</span>
                    <Badge variant={BADGE[TestResultView.tone(row)]} className="ml-auto">
                      {TestResultView.label(row)}
                    </Badge>
                  </div>
                  {row.feedback && <p className="text-sm">{row.feedback}</p>}
                  {TestResultView.source(row) && <p className="text-xs text-muted-foreground">{TestResultView.source(row)}</p>}
                  <Solution row={row} />
                </li>
              ))}
            </ol>
          </>
        )}
      </CardContent>
    </Card>
  );
}
