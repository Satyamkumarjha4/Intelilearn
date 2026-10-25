import type { Metadata } from "next";

import { LegalPage } from "@/components/legal/legal-page";
import { LegalFiles } from "@/lib/legal-files";

export const metadata: Metadata = { title: "Terms of Use" };

export default function TermsPage() {
  return <LegalPage title="Terms of Use" doc={LegalFiles.read("terms")} />;
}
