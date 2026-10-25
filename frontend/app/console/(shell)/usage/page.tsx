import type { Metadata } from "next";
import { Suspense } from "react";

import { UsageView } from "@/components/console/usage/usage-view";

export const metadata: Metadata = { title: "Usage & cost" };

export default function UsagePage() {
  // `useSearchParams` (every filter lives in the address) needs a Suspense boundary above it.
  return (
    <Suspense>
      <UsageView />
    </Suspense>
  );
}
