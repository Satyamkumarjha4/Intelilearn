"use client";

import dynamic from "next/dynamic";

import { Skeleton } from "@/components/ui/skeleton";

/** The code editor, loaded when a code question is on screen and never before: a page without one downloads none of it. */
export const CodeEditorLoader = dynamic(() => import("@/components/lessons/code-editor").then((m) => m.CodeEditor), {
  ssr: false,
  loading: () => <Skeleton className="h-48 rounded-xl" />,
});
