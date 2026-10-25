import type { Metadata } from "next";
import { Suspense } from "react";

import { LearnersView } from "@/components/console/people/learners-view";

export const metadata: Metadata = { title: "Learners" };

export default function LearnersPage() {
  // `useSearchParams` (the search lives in the address) needs a Suspense boundary above it.
  return (
    <Suspense>
      <LearnersView />
    </Suspense>
  );
}
