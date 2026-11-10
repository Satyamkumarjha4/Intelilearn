// The words of the landing page's sample Quick check (docs/reference/frontend.md, "The landing page"). Fixed on purpose:
// the sample makes no network call and no model call, so it can never be slow, cost anything or say something untested.

export type SampleQuestion = { question: string; options: string[]; answer: number; why: string };

/** What a score of 0, 1, 2 or 3 would give: the level, the three pages of the lesson and what its first page opens with. */
export type SampleLevel = { name: string; pages: string[]; snippet: string };

export const SAMPLE_TOPIC = "Trigonometry";

export const SAMPLE_QUESTIONS: SampleQuestion[] = [
  {
    question: "In a right triangle, which side is across from the right angle?",
    options: ["Hypotenuse", "Adjacent", "Opposite"],
    answer: 0,
    why: "The hypotenuse sits across from the right angle and is always the longest side.",
  },
  {
    question: "What is sin 30°?",
    options: ["1/2", "√3/2", "1"],
    answer: 0,
    why: "sin 30° = 1/2. It is one of the values worth knowing by heart.",
  },
  {
    question: "Which ratio is opposite ÷ adjacent?",
    options: ["Sine", "Cosine", "Tangent"],
    answer: 2,
    why: "Tangent is opposite over adjacent: tan = O/A.",
  },
];

/** Indexed by score: 0 right is a Beginner, 3 right an Expert. */
export const SAMPLE_LEVELS: SampleLevel[] = [
  { name: "Beginner", pages: ["Basics first", "Introduction", "Core"], snippet: "What an angle is, and how the three sides of a right triangle get their names." },
  { name: "Foundation", pages: ["Introduction", "Core", "A taste of advanced"], snippet: "Name the sides of a right triangle from the angle you care about, then meet sin, cos and tan." },
  { name: "Proficient", pages: ["Quick recap", "Core", "Advanced"], snippet: "A two-minute recap of sin, cos and tan, then straight into the rules you use in problems." },
  { name: "Expert", pages: ["Core", "Advanced", "Expert depth"], snippet: "The sine and cosine rules for any triangle, not just right-angled ones." },
];

export const SAMPLE_CAPTION = "Sample questions. Your real Quick check is written for the topic you pick.";
