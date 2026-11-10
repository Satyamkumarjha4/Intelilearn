import type { Metadata } from "next";

import { TestimonialsView } from "@/components/console/testimonials/testimonials-view";

export const metadata: Metadata = { title: "Testimonials" };

export default function TestimonialsPage() {
  return <TestimonialsView />;
}
