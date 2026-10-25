import type { Metadata } from "next";
import { Suspense } from "react";

import { AuditView } from "@/components/console/people/audit-view";

export const metadata: Metadata = { title: "Change log" };

export default function AuditPage() {
  // `useSearchParams` (the area filter lives in the address) needs a Suspense boundary above it.
  return (
    <Suspense>
      <AuditView />
    </Suspense>
  );
}
