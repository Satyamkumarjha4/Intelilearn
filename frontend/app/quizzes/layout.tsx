import type { Metadata } from "next";

export const metadata: Metadata = { title: "Quick quizzes" };

export default function QuizzesLayout({ children }: LayoutProps<"/quizzes">) {
  return children;
}
