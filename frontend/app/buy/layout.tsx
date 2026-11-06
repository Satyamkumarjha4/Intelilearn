import type { Metadata } from "next";

export const metadata: Metadata = { title: "Get more credits" };

export default function BuyLayout({ children }: LayoutProps<"/buy">) {
  return children;
}
