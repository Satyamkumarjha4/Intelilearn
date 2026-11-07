import type { Metadata } from "next";

import { CreditsView } from "@/components/console/credits/credits-view";

export const metadata: Metadata = { title: "Credits & prices" };

export default function CreditsPage() {
  return <CreditsView />;
}
