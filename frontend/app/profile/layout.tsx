import type { Metadata } from "next";

export const metadata: Metadata = { title: "Profile" };

export default function ProfileLayout({ children }: LayoutProps<"/profile">) {
  return children;
}
