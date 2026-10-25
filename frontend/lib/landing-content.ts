// The words on the public landing page (docs/frontend.md, "The landing page"). Static on purpose: the page is for people
// who are not signed in, so none of it comes from the API.

import type { DemoQuestion } from "@/lib/types";

export type Tone = "primary" | "marigold" | "insight";

export const LANDING_META = {
  title: "Socra · Learn only what you don't know yet",
  description:
    "Socra asks before it teaches. Pick any topic, answer a quick 10-question check, and get an interactive lesson that starts exactly where you are.",
};

export const NAV_LINKS = [
  { href: "#how", label: "How it works" },
  { href: "#paths", label: "Three ways forward" },
] as const;

/** The languages lessons come in, with the code that lets a screen reader pronounce each name. */
export const LANGUAGES = [
  { label: "English", lang: "en" },
  { label: "हिन्दी", lang: "hi" },
  { label: "Español", lang: "es" },
  { label: "Français", lang: "fr" },
  { label: "Deutsch", lang: "de" },
] as const;

// --- The hero's question ---------------------------------------------------------------------------------------------

/** The question shown when the API cannot give one (it is also in the question bank). */
export const HERO_FALLBACK_QUESTION: DemoQuestion = {
  id: 0,
  subject: "Maths",
  level_label: "Class 7",
  band: 2,
  question: "Which is larger: 3/4 or 2/3?",
  options: ["3/4", "2/3", "They are equal"],
  correct_index: 0,
  outcome_right: {
    level: 3,
    level_label: "Getting there",
    lesson_start: "Comparing fractions with different bottoms, using a common denominator.",
  },
  outcome_wrong: {
    level: 2,
    level_label: "Building up",
    lesson_start: "What a fraction means, and why bigger bottoms make smaller slices.",
  },
};

/** What the result card opens with, for a right answer and for anything else (wrong, or "I don't know"). */
export const HERO_EYEBROWS = { right: "Nice, that's right", notYet: "No problem, that's what the check is for" };

// --- How it works ----------------------------------------------------------------------------------------------------

export const WALK_STEPS = [
  { title: "Take a quick check", text: "10 questions, easy to hard. \"I don't know\" is a good answer.", caption: "The real quick check screen" },
  { title: "See your starting point", text: "What you know, where the gaps are, and where your lesson begins.", caption: "Your starting point, right after the check" },
  { title: "Learn with a lesson made for you", text: "Three pages with graphs and simulations you can play with.", caption: "A lesson page, with page flaps on the side" },
  { title: "Prove it in one test", text: "Feedback on every answer, and what to look at next.", caption: "Your test results and what to look at next" },
] as const;

export const WALK_PREVIEW = {
  check: {
    done: 5,
    total: 10,
    difficulty: { filled: 4, total: 5, label: "Hard" },
    question: "What does the Calvin cycle use to turn CO₂ into sugar?",
    options: ["Oxygen and water", "ATP and NADPH", "Chlorophyll and light"],
    picked: 1,
  },
  startingPoint: {
    eyebrow: "From your quick check · 6 of 10",
    title: "Your starting point",
    level: 3,
    levelLabel: "Getting there",
    known: ["Plants need sunlight", "Chlorophyll is green"],
    gaps: ["The Calvin cycle", "Limiting factors"],
  },
  book: { flaps: [{ label: "Intro", tone: "primary" }, { label: "Core", tone: "marigold" }, { label: "Advanced", tone: "insight" }] as const, active: 1 },
  result: {
    percent: 77,
    eyebrow: "Test complete",
    title: "Solid work!",
    text: "Two topics could use one more pass.",
    topic: "The Calvin cycle",
    why: "You mixed up which stage fixes CO₂.",
  },
} as const;

// --- Three ways forward ----------------------------------------------------------------------------------------------

export type PathId = "foundations" | "lesson" | "mastery";

export type PathSlide = {
  id: PathId;
  tone: Tone;
  tab: string;
  /** Lowest and highest quick-check score (out of 10) that lands on this path. */
  scores: [number, number];
  ifYouScore: string;
  heading: string;
  text: string;
  steps: string[];
  example: { initial: string; name: string; meta: string; score: number; lead: string; text: string };
};

export const PATH_INTRO = "Three learners asked about the same topic, Newton's laws of motion. Here's where their quick checks sent them.";

export const PATH_SLIDES: PathSlide[] = [
  {
    id: "foundations",
    tone: "marigold",
    tab: "0–2 correct",
    scores: [0, 2],
    ifYouScore: "0–2",
    heading: "We build your foundations first",
    text: "No point rushing ahead. A short check finds which basics are missing, and your lesson teaches those before the main topic.",
    steps: ["Quick check", "5-question foundations check", "Lesson: basics first, then the topic", "Final test"],
    example: {
      initial: "P",
      name: "Priya",
      meta: "Class 9 · Preparing for exams · हिन्दी",
      score: 2,
      lead: "Her lesson begins with",
      text: "What a force really is, using a cricket ball being hit, caught and dropped. Written in Hindi.",
    },
  },
  {
    id: "lesson",
    tone: "primary",
    tab: "3–9 correct",
    scores: [3, 9],
    ifYouScore: "3–9",
    heading: "You get a lesson that starts at your level",
    text: "We skip what you already know and start where your gaps begin. Higher score, deeper starting point.",
    steps: ["Quick check", "Your starting point", "3-page interactive lesson", "Final test"],
    example: {
      initial: "A",
      name: "Arjun",
      meta: "2nd year B.Tech · Interview prep · English",
      score: 7,
      lead: "His lesson begins with",
      text: "Free-body diagrams on a slope with friction, then the trick questions interviewers like.",
    },
  },
  {
    id: "mastery",
    tone: "insight",
    tab: "10 / 10",
    scores: [10, 10],
    ifYouScore: "10 / 10",
    heading: "You skip the lesson. You already know it.",
    text: "Pick a study sheet to keep it sharp instead. Add the other two any time.",
    steps: ["Quick check", "Choose: cheat, revision or practice sheet", "Download it as a PDF"],
    example: {
      initial: "M",
      name: "Meera",
      meta: "Class 12 · Revising for boards · English",
      score: 10,
      lead: "She picks",
      text: "A cheat sheet: all three laws, the key formulas and the common mistakes, on one page.",
    },
  },
];

// --- Proof strip -----------------------------------------------------------------------------------------------------

export type ProofIcon = "globe" | "shield" | "image" | "download";

export const PROOF_ITEMS: { icon: ProofIcon; tone: Tone; title: string; text: string }[] = [
  { icon: "globe", tone: "primary", title: "5 languages", text: "English, Hindi, Spanish, French, German" },
  { icon: "shield", tone: "insight", title: "Checked before you see it", text: "Every lesson is test-run in a safe sandbox" },
  { icon: "image", tone: "marigold", title: "Real, credited images", text: "Openly licensed pictures and diagrams" },
  { icon: "download", tone: "primary", title: "Keep it as a PDF", text: "Lessons and study sheets, offline" },
];

// --- Call to action and footer ---------------------------------------------------------------------------------------

export const CTA = {
  title: "What do you want to learn first?",
  text: "Type a topic. Your quick check is one step away.",
  placeholder: "e.g. Photosynthesis, Recursion, Ohm's law",
  maxLength: 200,
};

export const FOOTER_LINKS = [
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
  { href: "/contact", label: "Contact" },
] as const;

/** The signed-out visitor's way in. */
export const REGISTER_HREF = "/auth?mode=register";
export const SIGN_IN_HREF = "/auth";
