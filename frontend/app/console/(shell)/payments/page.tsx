import type { Metadata } from "next";

import { PaymentsView } from "@/components/console/payments/payments-view";

export const metadata: Metadata = { title: "Payments" };

export default function PaymentsPage() {
  return <PaymentsView />;
}
