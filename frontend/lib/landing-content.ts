// The words on the public landing page that are not numbers (docs/reference/frontend.md, "The landing page"). Every number a
// visitor sees (prices, credits, lessons, bonuses, question counts) comes from `GET /api/public/pricing`, never from here.

import { CONTACT } from "@/content/legal/contact";

export const LANDING_META = {
  title: "Socra · Learn anything, starting from what you already know",
  description: "A short Quick check finds your gaps. Socra teaches only those, then tests you. Start free, no card needed.",
};

export const NAV_LINKS = [
  { href: "#how", label: "How it works" },
  { href: "#features", label: "Features" },
  { href: "#pricing", label: "Pricing" },
  { href: "#faq", label: "FAQ" },
] as const;

/** The signed-out visitor's way in. */
export const REGISTER_HREF = "/auth?mode=register";
export const SIGN_IN_HREF = "/auth";
/** The signed-in visitor's way on. */
export const APP_HREF = "/lessons";

/** The marker cookie the API sets while someone is signed in (backend/accounts/cookies.py); it says nothing but that. */
export const SESSION_COOKIE = "lc_session";

export const HERO = {
  badge: "For school and college students, and anyone learning something new",
  title: "Learn anything, starting from what you already know.",
  text: "A short Quick check finds your gaps. Socra teaches only those, then tests you.",
  note: "Sign up, pick a topic, take the Quick check. No card needed, and your free credits never expire.",
  sampleBadge: "Try it now: 3 questions, no sign-up",
};

/** The last band: a topic typed here waits in `sessionStorage` through sign-up (lib/pending-topic.ts). */
export const CTA = {
  title: "Your first lessons are on us.",
  fallbackTitle: "What do you want to learn first?",
  text: "Pick a topic and see where you stand.",
  placeholder: "e.g. Photosynthesis, Ohm's law",
  maxLength: 200,
};

export const SUPPORT_EMAIL = CONTACT.email;

/** The footer's columns. "Refunds and credits" is the section of the Terms where refunds are explained. */
export const FOOTER_COLUMNS = [
  {
    title: "Product",
    links: [
      { label: "How it works", href: "/#how" },
      { label: "Pricing", href: "/#pricing" },
      { label: "FAQ", href: "/#faq" },
    ],
  },
  { title: "Company", links: [{ label: "Contact", href: `mailto:${CONTACT.email}` }] },
  {
    title: "Legal",
    links: [
      { label: "Terms", href: "/terms" },
      { label: "Privacy", href: "/privacy" },
      { label: "Refunds and credits", href: "/terms#credits-payments-and-tests" },
    ],
  },
] as const;
