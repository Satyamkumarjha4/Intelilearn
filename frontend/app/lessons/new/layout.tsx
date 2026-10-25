import type { Metadata } from "next";

export const metadata: Metadata = { title: "New lesson" };

export default function NewLessonLayout({ children }: LayoutProps<"/lessons/new">) {
  return children;
}
