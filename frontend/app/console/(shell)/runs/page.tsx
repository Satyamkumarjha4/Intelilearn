import type { Metadata } from "next";
import { Suspense } from "react";

import { RunsView } from "@/components/console/runs/runs-view";

export const metadata: Metadata = { title: "Lesson runs" };

export default function RunsPage() {
  // `useSearchParams` (the filters and the open run live in the address) needs a Suspense boundary above it.
  return (
    <Suspense>
      <RunsView />
    </Suspense>
  );
}
