import type { Metadata } from "next";

import { LegalPage } from "@/components/legal/legal-page";
import { LegalFiles } from "@/lib/legal-files";

export const metadata: Metadata = { title: "Privacy Policy" };

export default function PrivacyPage() {
  return <LegalPage title="Privacy Policy" doc={LegalFiles.read("privacy")} />;
}
