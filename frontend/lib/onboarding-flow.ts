import type { EducationLevel, Goal, LearningPreference, ProfileInput } from "@/lib/types";

export type Answers = Pick<ProfileInput, "education_level" | "grade_or_year" | "field_of_study" | "learning_preference" | "goal" | "preferred_language" | "notes">;
export type Choice = { value: string; label: string; description: string };
export type ApiChoice = { value: string; label: string };
export type FollowUp = { gradeQuestion: string | null; grades: string[]; fieldQuestion: string | null };

const STEPS = 5;
const NOTES_MAX = 2000;
const SCHOOL = ["Class 6", "Class 7", "Class 8", "Class 9", "Class 10", "Class 11", "Class 12"];
const YEARS = ["1st year", "2nd year", "3rd year", "4th year"];
const POSTGRAD = ["1st year", "2nd year", "Research"];

const STUDY: Record<string, string> = { school: "School", undergraduate: "College", postgraduate: "Postgraduate", professional: "Working", self_learner: "Self-learner" };
const GOAL: Record<string, string> = { exam_prep: "Exam prep", deep_understanding: "Deep understanding", quick_overview: "Quick overview", interview_prep: "Interview prep" };

/** The copy of the tiles: friendly words keyed by the value the API accepts. */
export const ONBOARDING_COPY = {
  education_level: [
    { value: "school", label: "School", description: "Class 6 to 12" },
    { value: "undergraduate", label: "College", description: "Undergraduate degree" },
    { value: "postgraduate", label: "Postgraduate", description: "Master's or PhD" },
    { value: "professional", label: "Working", description: "Learning for work" },
    { value: "self_learner", label: "Self-learner", description: "Learning on my own" },
  ],
  learning_preference: [
    { value: "visual", label: "Seeing it", description: "Graphs, diagrams and animations" },
    { value: "reading", label: "Reading it", description: "Clear written explanations" },
    { value: "hands_on", label: "Doing it", description: "Try things and practise" },
    { value: "mixed", label: "A mix", description: "A bit of everything" },
  ],
  goal: [
    { value: "exam_prep", label: "Prepare for an exam", description: "Focus on what is likely to be asked" },
    { value: "deep_understanding", label: "Understand deeply", description: "Go beyond the formulas" },
    { value: "quick_overview", label: "Quick overview", description: "The big picture, fast" },
    { value: "interview_prep", label: "Interview prep", description: "Questions you may be asked" },
  ],
  preferred_language: [
    { value: "en", label: "English", description: "" },
    { value: "hi", label: "हिन्दी", description: "" },
    { value: "es", label: "Español", description: "" },
    { value: "fr", label: "Français", description: "" },
    { value: "de", label: "Deutsch", description: "" },
  ],
} satisfies Record<string, Choice[]>;

const LANGUAGE_NAME = Object.fromEntries(ONBOARDING_COPY.preferred_language.map((c) => [c.value, c.label]));

const EMPTY: Answers = { education_level: "", grade_or_year: "", field_of_study: "", learning_preference: "", goal: "", preferred_language: "en", notes: "" };

/**
 * The five-step setup as a value: which step, what has been answered, and which way the last move went (for the slide).
 * Every change returns a new flow. Back is allowed here, unlike in a quiz. Step 4's Continue is where the profile is
 * saved, so that the lessons have it before step 5 suggests topics.
 */
export class OnboardingFlow {
  constructor(
    readonly step = 1,
    readonly answers: Answers = EMPTY,
    readonly direction: "forward" | "back" = "forward",
  ) {}

  /** What each study level asks next: a class or year (with its chips) and/or a field. */
  static followUp(level: string): FollowUp {
    switch (level) {
      case "school":
        return { gradeQuestion: "Which class are you in?", grades: SCHOOL, fieldQuestion: null };
      case "undergraduate":
        return { gradeQuestion: "Which year?", grades: YEARS, fieldQuestion: "What are you studying?" };
      case "postgraduate":
        return { gradeQuestion: "Which year?", grades: POSTGRAD, fieldQuestion: "What are you studying?" };
      case "professional":
        return { gradeQuestion: null, grades: [], fieldQuestion: "What field do you work in?" };
      case "self_learner":
        return { gradeQuestion: null, grades: [], fieldQuestion: "Anything you're focusing on? (optional)" };
      default:
        return { gradeQuestion: null, grades: [], fieldQuestion: null };
    }
  }

  /** A flow holding what a saved profile already says (and English where it says no language). */
  static fromProfile(profile: Partial<Answers>): OnboardingFlow {
    const answers = { ...EMPTY };
    for (const key of Object.keys(EMPTY) as (keyof Answers)[]) {
      const value = profile[key];
      if (typeof value === "string" && value !== "") answers[key] = value as never;
    }
    return new OnboardingFlow(1, answers);
  }

  /** Everything steps 1 to 4 ask for has been answered. */
  get complete(): boolean {
    return this.firstOpenStep === 5;
  }

  get canContinue(): boolean {
    const a = this.answers;
    switch (this.step) {
      case 1:
        return a.education_level !== "" && (OnboardingFlow.followUp(a.education_level).gradeQuestion === null || a.grade_or_year.trim() !== "");
      case 2:
        return a.learning_preference !== "";
      case 3:
        return a.goal !== "";
      case 4:
        return a.preferred_language !== "";
      default:
        return false; // step 5 has its own buttons
    }
  }

  /** Change answers. A new study level forgets what only made sense for the old one. */
  with(changes: Partial<Answers>): OnboardingFlow {
    const next: Answers = { ...this.answers, ...changes };
    if (changes.education_level !== undefined && changes.education_level !== this.answers.education_level) {
      const ask = OnboardingFlow.followUp(next.education_level);
      if (!ask.grades.includes(next.grade_or_year)) next.grade_or_year = changes.grade_or_year ?? "";
      if (ask.fieldQuestion === null) next.field_of_study = changes.field_of_study ?? "";
    }
    return new OnboardingFlow(this.step, next, this.direction);
  }

  next(): OnboardingFlow {
    return this.canContinue ? new OnboardingFlow(Math.min(this.step + 1, STEPS), this.answers, "forward") : this;
  }

  back(): OnboardingFlow {
    return new OnboardingFlow(Math.max(this.step - 1, 1), this.answers, "back");
  }

  goTo(step: number): OnboardingFlow {
    const target = Math.min(Math.max(Math.trunc(step), 1), STEPS);
    return new OnboardingFlow(target, this.answers, target < this.step ? "back" : "forward");
  }

  /** The body of `PUT /profile` (no name: that is the account's, not the setup's). */
  profile(): Omit<ProfileInput, "name"> {
    const a = this.answers;
    return {
      education_level: a.education_level as EducationLevel | "",
      grade_or_year: a.grade_or_year.trim(),
      field_of_study: a.field_of_study.trim(),
      learning_preference: a.learning_preference as LearningPreference | "",
      goal: a.goal as Goal | "",
      preferred_language: a.preferred_language,
      notes: a.notes.trim().slice(0, NOTES_MAX),
    };
  }

  /** What the server picks first topics from. */
  suggestionAnswers() {
    const { education_level, goal, preferred_language, grade_or_year, field_of_study } = this.profile();
    return { education_level, goal, preferred_language, grade_or_year, field_of_study };
  }

  /** What the topic suggestions are based on, as chips: "School · Class 9", "Exam prep", "हिन्दी". */
  summary(): string[] {
    const a = this.answers;
    const study = STUDY[a.education_level];
    const detail = a.grade_or_year.trim() || a.field_of_study.trim();
    return [study && (detail ? `${study} · ${detail}` : study), GOAL[a.goal], LANGUAGE_NAME[a.preferred_language]].filter((chip): chip is string => Boolean(chip));
  }

  /** The first step that has no answer yet (the furthest a saved place may be trusted). */
  get firstOpenStep(): number {
    for (let step = 1; step <= 4; step++) if (!new OnboardingFlow(step, this.answers).canContinue) return step;
    return 5;
  }
}

type Storage = Pick<globalThis.Storage, "getItem" | "setItem" | "removeItem">;

/** Keeps the setup in `sessionStorage` so a refresh resumes where it was. Works without storage. */
export class OnboardingStore {
  private static readonly KEY = "socra.onboarding";

  constructor(private readonly storage: Storage | null = OnboardingStore.browserStorage()) {}

  load(): OnboardingFlow | null {
    try {
      const raw: unknown = JSON.parse(this.storage?.getItem(OnboardingStore.KEY) ?? "null");
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
      const { step, answers } = raw as { step?: unknown; answers?: unknown };
      if (typeof step !== "number" || !answers || typeof answers !== "object" || Array.isArray(answers)) return null;
      const clean = { ...EMPTY };
      for (const key of Object.keys(EMPTY) as (keyof Answers)[]) {
        const value = (answers as Record<string, unknown>)[key];
        if (typeof value === "string") clean[key] = value as never;
      }
      const flow = new OnboardingFlow(1, clean);
      return flow.goTo(Math.min(step, flow.firstOpenStep));
    } catch {
      return null;
    }
  }

  save(flow: OnboardingFlow): void {
    try {
      this.storage?.setItem(OnboardingStore.KEY, JSON.stringify({ step: flow.step, answers: flow.answers }));
    } catch {
      // full or blocked: a refresh starts over
    }
  }

  clear(): void {
    try {
      this.storage?.removeItem(OnboardingStore.KEY);
    } catch {
      // nothing to forget
    }
  }

  private static browserStorage(): Storage | null {
    try {
      return typeof window === "undefined" ? null : window.sessionStorage;
    } catch {
      return null;
    }
  }
}

/** The tiles of a question: the usual copy for the values the API offers, plus any value only the API knows. */
export class OnboardingChoices {
  static merge(copy: Choice[], offered: ApiChoice[] | null | undefined): Choice[] {
    if (!offered) return copy;
    const known = new Map(copy.map((choice) => [choice.value, choice]));
    const ours = copy.filter((choice) => offered.some((o) => o.value === choice.value));
    const extra = offered.filter((o) => !known.has(o.value)).map((o): Choice => ({ value: o.value, label: o.label, description: "" }));
    return [...ours, ...extra];
  }
}
