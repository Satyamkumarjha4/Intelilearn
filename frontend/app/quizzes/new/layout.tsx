import type { Metadata } from "next";

export const metadata: Metadata = { title: "New quick quiz" };

export default function NewQuizLayout({ children }: LayoutProps<"/quizzes/new">) {
  return children;
}
