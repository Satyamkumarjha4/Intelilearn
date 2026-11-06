import type { Metadata } from "next";

export const metadata: Metadata = { title: "Your streak" };

export default function StreakLayout({ children }: LayoutProps<"/streak">) {
  return children;
}
