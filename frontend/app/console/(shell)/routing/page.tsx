import type { Metadata } from "next";
import { Suspense } from "react";

import { RoutingView } from "@/components/console/routing/routing-view";

export const metadata: Metadata = { title: "Model routing" };

export default function RoutingPage() {
  // `useSearchParams` (the selected step lives in the address) needs a Suspense boundary above it.
  return (
    <Suspense>
      <RoutingView />
    </Suspense>
  );
}
