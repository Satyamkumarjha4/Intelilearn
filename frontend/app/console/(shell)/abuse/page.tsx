import type { Metadata } from "next";

import { AbuseView } from "@/components/console/signin/abuse-view";

export const metadata: Metadata = { title: "Sign-up abuse" };

export default function AbusePage() {
  return <AbuseView />;
}
