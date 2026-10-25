"use client";

import { ArrowRightIcon, MoreHorizontalIcon, Trash2Icon } from "lucide-react";
import Link from "next/link";

import { StatusPill } from "@/components/lessons/status-pill";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { ReadPages } from "@/lib/lesson-book";
import { LessonStatus } from "@/lib/lesson-status";
import type { LessonSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = { lesson: LessonSummary; onDelete: (lesson: LessonSummary) => void };

/** One lesson in the list: its title, what kind it is, where it stands as a sentence, and the one thing to do next. */
export function LessonCard({ lesson, onDelete }: Props) {
  const title = lesson.title || lesson.topic;
  const pill = LessonStatus.of(lesson, new ReadPages(lesson.id).load().size);
  return (
    <Card className="relative h-full motion-safe:transition-[transform,box-shadow] motion-safe:hover:-translate-y-0.5 motion-safe:hover:shadow-[0_4px_0_var(--border)]">
      <CardContent className="flex h-full flex-col gap-3 px-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 flex-col gap-0.5">
            <Link
              href={`/lessons/${lesson.id}`}
              className="rounded-md font-heading text-lg leading-snug font-semibold outline-none after:absolute after:inset-0 after:content-[''] focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <span className="line-clamp-2">{title}</span>
            </Link>
            <p className="text-xs text-muted-foreground">{LessonStatus.kind(lesson)}</p>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger
              className={cn(buttonVariants({ variant: "ghost", size: "icon-sm" }), "relative z-10 -mt-1 -mr-2")}
              aria-label={`More options for ${title}`}
            >
              <MoreHorizontalIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuItem variant="destructive" onClick={() => onDelete(lesson)}>
                <Trash2Icon /> Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <div>
          <StatusPill pill={pill} />
        </div>
        <div className="mt-auto flex items-center justify-between gap-2 border-t border-dashed border-border pt-3 text-sm">
          <span className="text-muted-foreground">{LessonStatus.ago(lesson.updated_at)}</span>
          <span className="flex items-center gap-1 font-extrabold text-primary-text">
            {pill.action} <ArrowRightIcon className="size-4" aria-hidden="true" />
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
