import type { Metadata } from "next";

export const metadata: Metadata = { title: "Your credits" };

export default function WalletLayout({ children }: LayoutProps<"/wallet">) {
  return children;
}
