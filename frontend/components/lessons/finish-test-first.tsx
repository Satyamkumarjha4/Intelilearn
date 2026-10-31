import { LockIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { TestGuard } from "@/lib/test-guard";

/** What the lesson's pages and study sheets show while the learner is in the middle of the test. */
export function FinishTestFirst({ onGoToTest }: { onGoToTest: () => void }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 px-6 py-8 text-center">
        <LockIcon className="size-9 text-marigold-deep" aria-hidden="true" />
        <h2 className="font-heading text-2xl font-semibold">{TestGuard.TITLE}</h2>
        <p className="max-w-prose text-muted-foreground">{TestGuard.TEXT}</p>
        <Button variant="marigold" onClick={onGoToTest}>
          {TestGuard.BUTTON}
        </Button>
      </CardContent>
    </Card>
  );
}
