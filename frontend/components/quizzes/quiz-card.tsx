"use client";

import { ArrowRightIcon, MoreHorizontalIcon, Trash2Icon } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { QuizList } from "@/lib/quiz-list";
import type { QuizSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = { quiz: QuizSummary; onDelete: (quiz: QuizSummary) => void };

/** One quick quiz in the list: its topic, what it is made from, where it stands, and the one thing to do next. */
export function QuizCard({ quiz, onDelete }: Props) {
  const status = QuizList.status(quiz);
  return (
    <Card className="relative h-full motion-safe:transition-[transform,box-shadow] motion-safe:hover:-translate-y-0.5 motion-safe:hover:shadow-[0_4px_0_var(--border)]">
      <CardContent className="flex h-full flex-col gap-3 px-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 flex-col gap-0.5">
            <Link
              href={`/quizzes/${quiz.id}`}
              className="rounded-md font-heading text-lg leading-snug font-semibold outline-none after:absolute after:inset-0 after:content-[''] focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <span className="line-clamp-2">{quiz.topic}</span>
            </Link>
            <p className="text-xs text-muted-foreground">{QuizList.kind(quiz)}</p>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger
              className={cn(buttonVariants({ variant: "ghost", size: "icon-sm" }), "relative z-10 -mt-1 -mr-2")}
              aria-label={`More options for ${quiz.topic}`}
            >
              <MoreHorizontalIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuItem variant="destructive" onClick={() => onDelete(quiz)}>
                <Trash2Icon /> Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <div>
          <Badge variant={status.tone}>{status.label}</Badge>
        </div>
        <div className="mt-auto flex items-center justify-between gap-2 border-t border-dashed border-border pt-3 text-sm">
          <span className="text-muted-foreground">{QuizList.facts(quiz)}</span>
          <span className="flex items-center gap-1 font-extrabold text-primary-text">
            {status.action} <ArrowRightIcon className="size-4" aria-hidden="true" />
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
