import type { Metadata } from "next";

import { VerificationView } from "@/components/console/signin/verification-view";

export const metadata: Metadata = { title: "Learner sign-in" };

export default async function LearnerVerificationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <VerificationView learnerId={id} />;
}
