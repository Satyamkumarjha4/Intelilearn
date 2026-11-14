import type { Metadata } from "next";

import { SignupsView } from "@/components/console/signin/signups-view";

export const metadata: Metadata = { title: "Waiting for a code" };

export default function SignupsPage() {
  return <SignupsView />;
}
