// Mirrors the API (see docs/api.md and Swagger at /api/docs).

export type User = {
  id: string;
  email: string;
  name: string;
  profile_complete: boolean;
};

export type EducationLevel = "school" | "undergraduate" | "postgraduate" | "professional" | "self_learner";
export type LearningPreference = "visual" | "reading" | "hands_on" | "mixed";
export type Goal = "exam_prep" | "deep_understanding" | "quick_overview" | "interview_prep";

export type Profile = {
  name: string;
  email: string;
  education_level: EducationLevel | "";
  grade_or_year: string;
  field_of_study: string;
  preferred_language: string;
  learning_preference: LearningPreference | "";
  goal: Goal | "";
  notes: string;
  profile_complete: boolean;
  updated_at: string;
};

export type ProfileInput = Omit<Profile, "email" | "profile_complete" | "updated_at">;

// --- Lessons (docs/api.md) ---

export type Stage =
  | "preparing_diagnostic"
  | "awaiting_diagnostic"
  | "awaiting_prerequisite"
  | "awaiting_choice"
  | "generating_material"
  | "generating_lesson"
  | "ready"
  | "failed";

export type Route = "prerequisite" | "lesson" | "mastery";
export type QuizKind = "diagnostic" | "prerequisite";
export type Band = "basic" | "easy_moderate" | "moderate" | "moderate_hard" | "hard";

export type LessonSummary = {
  id: string;
  topic: string;
  stage: Stage;
  route: Route | "";
  title: string;
  level: string;
  created_at: string;
  updated_at: string;
};

export type QuizResultSummary = {
  correct: number;
  total: number;
  dont_know: number;
  by_band: Partial<Record<Band, [number, number]>>;
  route?: Route;
};

export type Assessment = {
  level: string;
  known_concepts: string[];
  gaps: string[];
  start_point: string;
  confidence: string;
};

export type LessonDetail = LessonSummary & {
  user_context: string;
  error: string;
  warnings: string[];
  assessment: Assessment | null;
  prerequisites_to_cover: string[];
  active_run_id: string | null;
  results: Record<QuizKind, QuizResultSummary | null>;
  materials: MaterialKind[];
};

export type Page<T> = { results: T[]; next: string | null; previous: string | null };

export type LearnerQuestion = { id: string; band?: Band; question: string; options: string[] };
export type QuizForLearner = { quiz_id: string; kind: QuizKind; questions: LearnerQuestion[]; allow_dont_know: boolean };
export type Answer = number | "dont_know";

export type ReviewQuestion = LearnerQuestion & {
  correct_index: number;
  explanation: string;
  answer: Answer;
  correct: boolean;
};
export type QuizReview = { quiz_id: string; kind: QuizKind; questions: ReviewQuestion[]; result: QuizResultSummary };

export type RunStatus = "queued" | "running" | "paused" | "succeeded" | "failed" | "cancelled";

export type RunEventName = "snapshot" | "node" | "model" | "warning" | "awaiting_input" | "done" | "error" | "cancelled";
export type NodeStatus = "pending" | "running" | "done" | "retrying" | "degraded" | "failed";

export type RunSnapshot = {
  status: RunStatus;
  stage: Stage;
  lesson_id: string;
  node_status: Record<string, NodeStatus>;
  error: string;
  awaiting: "diagnostic" | "prerequisite" | "mastery_choice" | null;
};

export type RunEvent =
  | { name: "snapshot"; data: RunSnapshot }
  | { name: "node"; data: { node: string; status: NodeStatus; attempt?: number; reason?: string } }
  | { name: "model"; data: { node: string; model: string; kind: "retry" | "fallback"; reason: string } }
  | { name: "warning"; data: { message: string } }
  | { name: "awaiting_input"; data: { kind: string; quiz_id?: string } }
  | { name: "done"; data: { lesson_id: string; stage: Stage } }
  | { name: "error"; data: { message: string; code: string } }
  | { name: "cancelled"; data: Record<string, never> };

// --- Study sheets (docs/lesson-graph.md, docs/api.md) ---

export type MaterialKind = "cheat_sheet" | "revision_sheet" | "practice_sheet";

export type CheatItem = {
  label: string;
  kind: "formula" | "rule" | "term" | "fact" | "pattern";
  content: string;
  formula: string;
  variables: { symbol: string; meaning: string }[];
  when_to_use: string;
};
export type CheatSheet = { title: string; summary: string; sections: { heading: string; items: CheatItem[] }[] };

export type WorkedExample = { problem: string; solution: string };
export type RevisionSheet = {
  title: string;
  overview: string;
  subtopics: {
    title: string;
    summary: string;
    key_points: string[];
    worked_examples: WorkedExample[];
    common_mistakes: string[];
  }[];
  final_tips: string[];
};

export type QuestionType = "mcq" | "numerical" | "short_answer" | "long_answer" | "code";
export type PracticeQuestion = {
  id: string;
  type: QuestionType;
  concept: string;
  difficulty: "easy" | "medium" | "hard";
  marks: number;
  question: string;
  options?: string[];
  unit?: string;
  language?: string;
  starter_code?: string;
};
export type PracticeSheet = { title: string; instructions: string; questions: PracticeQuestion[] };

export type Solution = {
  correct_index?: number;
  answer?: number;
  tolerance?: number;
  unit?: string;
  model_answer?: string;
  key_points?: string[];
  rubric?: string[];
  reference_solution?: string;
};

export type StudyMaterial<T> = { kind: MaterialKind; content: T; solutions: Record<string, Solution> };

export type PracticeGrade = {
  score: { awarded: number; available: number; open_marks: number; correct: number; marked: number };
  results: { id: string; correct: boolean | null; marks: number; awarded: number | null; solution: Solution }[];
};
