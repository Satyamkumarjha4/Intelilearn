import type { Metadata } from "next";
import { Suspense } from "react";

import { OverviewView } from "@/components/console/overview/overview-view";

// Same segment as the layout, so the layout's title template does not apply to it.
export const metadata: Metadata = { title: "Overview · Console" };

export default function OverviewPage() {
  // `useSearchParams` (the range lives in the address) needs a Suspense boundary above it.
  return (
    <Suspense>
      <OverviewView />
    </Suspense>
  );
}
