import type { Metadata } from "next";

import { WalletView } from "@/components/console/people/wallet-view";

export const metadata: Metadata = { title: "Wallet" };

export default async function LearnerWalletPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <WalletView learnerId={id} />;
}
