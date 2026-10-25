import type { Metadata } from "next";

import { ContactPage } from "@/components/contact/contact-page";
import { LegalShell } from "@/components/legal/legal-page";

export const metadata: Metadata = { title: "Contact" };

export default function Contact() {
  return (
    <LegalShell>
      <ContactPage />
    </LegalShell>
  );
}
