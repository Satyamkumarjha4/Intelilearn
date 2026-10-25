import { ChevronRightIcon } from "lucide-react";
import Link from "next/link";

import { JourneyStepper } from "@/components/lessons/journey-stepper";
import { Badge } from "@/components/ui/badge";
import { Journey } from "@/lib/journey";
import type { LessonDetail } from "@/lib/types";

/** The top of every lesson screen: where you are in the app, what the lesson is, and where you are in the journey. */
export function LessonHeader({ lesson }: { lesson: LessonDetail }) {
  const title = lesson.title || lesson.topic;
  const tag = Journey.tag(lesson);
  return (
    <header className="flex flex-col gap-4">
      <nav aria-label="Breadcrumb">
        <ol className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <li>
            <Link href="/lessons" className="rounded-md font-semibold hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none">
              My lessons
            </Link>
          </li>
          <li aria-hidden="true">
            <ChevronRightIcon className="size-4" />
          </li>
          <li aria-current="page" className="min-w-0 truncate">
            {lesson.topic}
          </li>
        </ol>
      </nav>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="font-heading text-3xl font-semibold tracking-tight">{title}</h1>
        {tag && <Badge variant="insight">{tag}</Badge>}
      </div>
      <JourneyStepper steps={Journey.of(lesson)} />
    </header>
  );
}
