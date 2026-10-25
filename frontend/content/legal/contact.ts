/**
 * The words of the Contact page, from docs/legal/socra-legal-copy.md. Edit them here: the page only lays them out.
 * The email below is the only address anywhere in the product.
 */
export const CONTACT = {
  email: "satyamjha4@gmail.com",
  heading: "Get in touch",
  intro: "Socra is built and run by Satyam Jha. Email is the fastest way to reach us. We usually reply within 2–3 working days.",
  topicsHeading: "Choose a topic",
  grievance: { title: "Grievance officer (DPDP Act)", text: "Satyam Jha · satyamjha4@gmail.com · acknowledgement within 48 hours, resolution within 30 days." },
} as const;

export type ContactTopic = { id: string; title: string; subject: string; helper: string };

export const CONTACT_TOPICS: ContactTopic[] = [
  { id: "lesson", title: "Report a problem in a lesson", subject: "[Socra] Lesson problem", helper: "Include the lesson link and the page, and what looked wrong." },
  { id: "account", title: "Account or sign-in help", subject: "[Socra] Account help", helper: "Write from the email you signed up with." },
  {
    id: "privacy",
    title: "Privacy or data request",
    subject: "[Socra] Privacy request",
    helper: "Ask for a copy of your data, a correction or deletion. Send it from your account email. We reply within 30 days.",
  },
  { id: "feedback", title: "Feedback and ideas", subject: "[Socra] Feedback", helper: "What would make Socra more useful for you?" },
  { id: "parents", title: "Parents and teachers", subject: "[Socra] Parent / teacher", helper: "Questions about students under 18, consent or classroom use." },
];
