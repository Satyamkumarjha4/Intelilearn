import { ChevronRightIcon, CornerUpLeftIcon, SproutIcon, TrendingUpIcon } from "lucide-react";
import Link from "next/link";

import { JourneyStepper } from "@/components/lessons/journey-stepper";
import { Badge } from "@/components/ui/badge";
import { FollowupLinks } from "@/lib/followup-links";
import { Journey } from "@/lib/journey";
import type { LessonDetail } from "@/lib/types";

/** The top of every lesson screen: where you are in the app, what the lesson is, and where you are in the journey. */
export function LessonHeader({ lesson }: { lesson: LessonDetail }) {
  const title = lesson.title || lesson.topic;
  const tag = Journey.tag(lesson);
  const links = FollowupLinks.of(lesson);
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
      {FollowupLinks.any(links) && (
        <ul aria-label="Related lessons" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          {links.madeFrom && (
            <li className="flex items-center gap-1.5">
              <CornerUpLeftIcon className="size-4 text-muted-foreground" aria-hidden="true" />
              <span className="text-muted-foreground">{links.madeFrom.label}:</span>
              <Link href={links.madeFrom.href} className="rounded-md font-semibold underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50">
                {links.madeFrom.title}
              </Link>
            </li>
          )}
          {links.followups.map((link) => (
            <li key={link.href} className="flex items-center gap-1.5">
              {link.label === "Foundation lesson" ? (
                <SproutIcon className="size-4 text-marigold-text" aria-hidden="true" />
              ) : (
                <TrendingUpIcon className="size-4 text-primary-text" aria-hidden="true" />
              )}
              <span className="text-muted-foreground">{link.label}:</span>
              <Link href={link.href} className="rounded-md font-semibold underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50">
                {link.title}
              </Link>
            </li>
          ))}
        </ul>
      )}
      <JourneyStepper steps={Journey.of(lesson)} />
    </header>
  );
}
