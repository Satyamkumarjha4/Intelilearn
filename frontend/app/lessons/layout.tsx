import type { Metadata } from "next";

export const metadata: Metadata = { title: "My lessons" };

export default function LessonsLayout({ children }: LayoutProps<"/lessons">) {
  return children;
}
