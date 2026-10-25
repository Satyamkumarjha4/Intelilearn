// Mirrors the API (see docs/api.md and Swagger at /api/docs).

export type User = {
  id: string;
  email: string;
  name: string;
  profile_complete: boolean;
  /** Staff may use the console (`/api/console`); everyone else gets a 404 there. */
  is_staff: boolean;
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

// --- The landing page (docs/api.md) ---

export type DemoOutcome = { level: number; level_label: string; lesson_start: string };

/** A question of the landing page's try-it card (`GET /landing/demo-question`). */
export type DemoQuestion = {
  id: number;
  subject: string;
  level_label: string;
  /** Difficulty, 1 (Basics) to 5 (Expert). */
  band: number;
  question: string;
  options: string[];
  correct_index: number;
  outcome_right: DemoOutcome;
  outcome_wrong: DemoOutcome;
};

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
  test_status: TestStatus;
  /** Only once the test is graded; null before that. */
  test_score: TestScore | null;
  /** How many study sheets a mastery lesson has. */
  material_count: number;
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
  test_status: TestStatus;
  /** Only once the grading has finished; null before that. */
  test_score: TestScore | null;
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
export type QuizReview = {
  quiz_id: string;
  kind: QuizKind;
  questions: ReviewQuestion[];
  result: QuizResultSummary;
  submitted_at: string;
};

export type RunStatus = "queued" | "running" | "paused" | "succeeded" | "failed" | "cancelled";

export type RunEventName = "snapshot" | "node" | "model" | "warning" | "awaiting_input" | "done" | "error" | "cancelled";
export type NodeStatus = "pending" | "running" | "done" | "retrying" | "degraded" | "failed";

export type RunSnapshot = {
  status: RunStatus;
  stage: Stage;
  lesson_id: string;
  node_status: Record<string, NodeStatus>;
  error: string;
  /** When the run began (else when it was queued). */
  started_at?: string;
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

/** The media entry the lesson runtime reads (`LESSON.media[id]`). */
export type LessonMedia = {
  url: string;
  kind: string;
  alt: string;
  caption: string;
  attribution: string;
  license: string;
  source_url: string;
  width: number;
  height: number;
};

/** `GET /lessons/{id}/document`: what the sandbox runs and the data it renders. */
export type LessonDocument = {
  code: string;
  code_version: number;
  /** A lesson made before the test became its own screen still has it as a page in its code: hide that page. */
  has_embedded_test: boolean;
  data: { media: Record<string, LessonMedia> } & Record<string, unknown>;
};

export type RepairError = { message: string; stack?: string; page?: string };
export type LessonVersion = { code_version: number; reason: string; created_at: string };

/** One section of a lesson page (`LESSON.pages.<key>.sections`), as the page writer produced it. */
export type LessonSection = {
  id: string;
  heading: string;
  body: string;
  key_points: string[];
  worked_examples: { problem: string; solution: string }[];
  formulas: { latex: string; explanation: string }[];
  code_snippets: { language: string; code: string; explanation: string }[];
  callouts: { kind: "note" | "tip" | "warning" | "example"; text: string }[];
};
export type LessonPageContent = { key: string; title: string; sections: LessonSection[]; summary: string };

export type QuestionResult = {
  id: string;
  type: QuestionType;
  concept: string;
  marks: number;
  /** null while a model is still grading it. */
  awarded: number | null;
  correct: boolean | null;
  graded_by: "auto" | "model" | "none";
  feedback: string;
  solution: Record<string, unknown>;
};
/** What a submitted lesson test scored (`TestSubmission.result`). */
export type ScoreCard = {
  complete: boolean;
  score: { awarded: number; available: number; percent: number };
  questions: QuestionResult[];
  topics_to_revisit: string[];
};
export type TestSubmission = {
  id: string;
  status: "grading" | "graded" | "failed";
  error: string;
  /** The learner's own answers, {question_id: answer}. */
  answers: Record<string, unknown>;
  result: ScoreCard | null;
  submitted_at: string;
  graded_at: string | null;
};

export type TestStatus = "not_started" | TestSubmission["status"];
export type TestScore = { awarded: number; available: number };

/** A question of the test screen (`GET /lessons/{id}/test`): no answer, marking scheme or concept. */
export type LearnerTestQuestion = {
  id: string;
  type: QuestionType;
  question: string;
  marks: number;
  options?: string[];
  unit?: string;
  language?: string;
  starter_code?: string;
};
/** `GET /lessons/{id}/test`. The test can be submitted once; `submission` is set after that. */
export type LearnerTest = {
  questions: LearnerTestQuestion[];
  total_marks: number;
  submission: { id: string; status: TestSubmission["status"]; submitted_at: string } | null;
};
export type TestSubmissionCreated = { submission_id: string; run_id: string | null; status: TestSubmission["status"] };


// --- The console (staff only, /api/console; docs/api.md) -------------------------------------------------------------

/** US dollars as a decimal string with six places, for example "0.012345" (`Number()` it only to draw). */
export type Money = string;
export type ConsoleRange = "today" | "7d" | "30d";
export type ConsoleGraph = "flow" | "study_material" | "runtime_repair" | "grade_test";
export type RunTrigger =
  | "start"
  | "resume_diagnostic"
  | "resume_prerequisite"
  | "resume_choice"
  | "retry"
  | "repair"
  | "grade"
  | "extra_material";
export type Effort = "none" | "low" | "medium" | "high";
export type NodePhase = "diagnose" | "author" | "build" | "post" | "onboarding";
/** worked first time, worked on a retry (attempt above 1), or did not work (any other status). */
export type CallOutcome = "ok" | "retried" | "failed";
export type CallStatus = "ok" | "retryable_error" | "fatal_error" | "invalid_output";

export type HealthComponent = { ok: boolean; latency_ms: number; detail: string };
export type ConsoleHealth = {
  status: "ok" | "degraded";
  database: HealthComponent;
  redis: HealthComponent;
  celery: HealthComponent;
  /** Celery workers that answered a ping. */
  workers: number;
};

export type AttentionKind = "lessons_failed" | "model_failing" | "rate_limit_waits" | "provider_key_missing";
export type Attention = {
  kind: AttentionKind;
  severity: "error" | "warning" | "info";
  title: string;
  detail: string;
  /** A console page, as a path with its query, for example "/console/runs?status=failed". */
  link: string;
};

export type ConsoleOverview = {
  range: ConsoleRange;
  period: { start: string; end: string };
  health: ConsoleHealth;
  lessons: { started: number; finished: number; failed: number; previous_started: number; previous_finished: number };
  spend: { range_total: Money; per_lesson_avg: Money; month_to_date: Money; monthly_budget: Money };
  /** ok + retried + failed = total; fallbacks are attempts on a step's later models, of any result. */
  calls: { total: number; ok: number; retried: number; failed: number; fallbacks: number };
  /** 14 days (30 for 30d), oldest first, empty days included. */
  daily_spend: { date: string; by_provider: Record<string, Money> }[];
  /** The same days: lessons started, and model calls made and worked (ok on any attempt), for sparklines. */
  daily_activity: { date: string; lessons_started: number; calls_total: number; calls_worked: number }[];
  funnel: {
    started: number;
    quick_check_done: number;
    built: number;
    test_submitted: number;
    study_sheets: number;
    failed_building: number;
    waiting: number;
  };
  slowest_steps: { node: string; p95_s: number }[];
  /** Most serious first. */
  attention: Attention[];
};

/** `custom` is whole days from `start` to `end` (both YYYY-MM-DD, `end` included, at most a year). */
export type UsageRange = ConsoleRange | "custom";
export type UsageFilters = {
  range?: UsageRange;
  start?: string;
  end?: string;
  provider?: string;
  model?: string;
  node?: string;
  outcome?: CallOutcome | "";
};
export type ConsoleUsage = {
  range: UsageRange;
  period: { start: string; end: string };
  kpis: {
    calls: number;
    tokens_in: number;
    tokens_out: number;
    spend: Money;
    /** Of the calls that worked; null if none did. */
    median_latency_s: number | null;
    p95_latency_s: number | null;
  };
  by_model: {
    model: string;
    provider: string;
    median_s: number | null;
    p95_s: number | null;
    ok: number;
    retried: number;
    failed: number;
    calls: number;
    spend: Money;
  }[];
  by_node: {
    node: string;
    calls: number;
    ok_pct: number;
    retries: number;
    fallbacks: number;
    tokens_k: number;
    spend: Money;
    p95_s: number | null;
  }[];
};

export type RunRow = {
  id: string;
  lesson_id: string;
  topic: string;
  learner_name: string;
  graph: ConsoleGraph;
  trigger: RunTrigger;
  status: RunStatus;
  /** Where the lesson itself is. */
  stage: Stage;
  /** So far for a run in progress; null if it has not started. */
  duration_s: number | null;
  calls: number;
  cost: Money;
  created_at: string;
};
export type RunQuery = { status?: RunStatus | RunStatus[] | ""; graph?: ConsoleGraph | ConsoleGraph[] | ""; q?: string };
export type TimelineState = "ran" | "retried" | "failed" | "waiting";
export type TimelineStep = {
  node: string;
  phase: "diagnose" | "author" | "build" | "post" | "other";
  /** Seconds after the run started; null for a run from before times were kept. */
  start_offset_s: number | null;
  /** Null while waiting for the learner, or when unknown. */
  duration_s: number | null;
  state: TimelineState;
};
export type RunModelCall = {
  id: number;
  created_at: string;
  node: string;
  provider: string;
  model: string;
  attempt: number;
  fallback_index: number;
  status: CallStatus;
  outcome: CallOutcome;
  latency_s: number;
  tokens_in: number | null;
  tokens_out: number | null;
  tool_calls: number;
  cost: Money | null;
  error: string;
};
export type RunDetail = RunRow & {
  error: string;
  started_at: string | null;
  finished_at: string | null;
  timeline: TimelineStep[];
  /** The last 20, newest first. */
  model_calls: RunModelCall[];
  can_retry: boolean;
  can_cancel: boolean;
};

export type ConsoleProvider = {
  key: string;
  kind: string;
  /** The name of the environment variable holding the key. The key itself is never sent. */
  api_key_env: string;
  api_key_set: boolean;
  base_url: string;
  rpm_limit: number | null;
  enabled: boolean;
  models_count: number;
  spend_7d: Money;
};
export type ProviderChanges = Partial<Pick<ConsoleProvider, "rpm_limit" | "base_url" | "enabled">>;

export type ProbeCheck = { capability: string; ok: boolean; latency_s: number; detail: string };
export type ProbeResult = { ok: boolean; latency_s: number | null; error: string | null; checks: ProbeCheck[] };
export type ModelCapabilities = {
  supports_structured_output: boolean;
  structured_output_method: "json_schema" | "function_calling" | "json_mode";
  supports_tool_calling: boolean;
  supports_parallel_tool_calls: boolean;
  supports_vision: boolean;
  supports_reasoning: boolean;
  reasoning_control: "effort" | "budget_tokens" | "none";
  reasoning_disables_sampling: boolean;
};
export type ConsoleModelFields = ModelCapabilities & {
  name: string;
  label: string;
  enabled: boolean;
  default_params: Record<string, unknown>;
  context_window: number;
  max_output_tokens: number;
  rpm_limit: number | null;
  /** US dollars per million tokens, for example "0.1500". */
  input_cost_per_mtok: string | null;
  output_cost_per_mtok: string | null;
};
export type ConsoleModel = ConsoleModelFields & {
  id: number;
  /** The provider's key. */
  provider: string;
  api_key_set: boolean;
  /** The steps (node keys) that use it. */
  bound_nodes: string[];
  last_probe: { at: string; ok: boolean; latency_s: number | null; error: string } | null;
};
/** To add a model; only `provider` and `name` are required. */
export type NewModel = Partial<ConsoleModelFields> & { provider: string; name: string };
/** To change one; its provider cannot change. */
export type ModelChanges = Partial<ConsoleModelFields>;
/** The 409 `model_in_use` error carries the steps in `extra.nodes`. */
export type ModelInUseExtra = { nodes: string[] };

export type BindingOverrides = { params: Record<string, unknown>; reasoning_effort: Effort | "" };
/** A model in a step's chain, as sent when saving. The chain's order is its priority. */
export type BindingInput = { model: number; enabled?: boolean; max_retries?: number; overrides?: Partial<BindingOverrides> };
export type RoutingBinding = {
  /** The model's id; null for a model a profile names that the registry lacks. */
  model: number | null;
  /** provider/name */
  model_label: string;
  enabled: boolean;
  max_retries: number;
  overrides: BindingOverrides;
  /** Why this model cannot serve this step; empty if it can. */
  problems: string[];
};
export type NodeRouting = {
  key: string;
  phase: NodePhase;
  description: string;
  /** Optional steps can be switched off; required ones cannot. */
  optional: boolean;
  output: "structured" | "tools" | "text";
  /** Capabilities a model needs for this step. */
  requires: string[];
  min_output_tokens: number;
  min_context: number;
  enabled: boolean;
  reasoning_effort: Effort;
  max_attempts: number;
  max_tool_steps: number | null;
  timeout_s: number;
  params_override: Record<string, unknown>;
  /** In priority order. */
  bindings: RoutingBinding[];
};
/** `PUT /nodes/{key}`: the whole routing of a step (a save replaces what was there). */
export type NodeRoutingInput = {
  enabled: boolean;
  reasoning_effort: Effort;
  max_attempts: number;
  max_tool_steps?: number | null;
  timeout_s: number;
  params_override?: Record<string, unknown>;
  bindings: BindingInput[];
};
export type ConsoleRouting = { phases: { phase: NodePhase; nodes: NodeRouting[] }[] };

export type RoutingProfile = { name: string; label: string; description: string; nodes: number };
export type ProfilePreview = {
  profile: string;
  label: string;
  nodes: { key: string; changed: boolean; current: NodeRouting; proposed: NodeRouting; problems: string[] }[];
  summary: { total: number; changed: number; blocked: number };
};

export type RoutingThresholds = {
  /** Questions in the quick check. */
  questions_total: number;
  /** A score at or below this goes to the foundations first. */
  foundations_max: number;
  /** The lowest score that can count as mastery. */
  mastery_min: number;
};
export type FlowSettingsValues = {
  diagnostic_questions_per_band: number;
  prerequisite_question_count: number;
  prereq_trigger_max_correct: number;
  mastery_requires_all_correct: boolean;
  final_test_min: number;
  final_test_max: number;
  max_interactives_per_page: number;
  alignment_min_score: number;
  alignment_max_rounds: number;
  render_check_max_rounds: number;
  max_auto_runtime_repairs: number;
  media_sources: string[];
  allowed_media_licenses: string[];
};
export type ConsoleFlowSettings = FlowSettingsValues & { routing_thresholds: RoutingThresholds };

export type ConsoleLearner = {
  id: string;
  name: string;
  email: string;
  education_level: EducationLevel | "";
  grade_or_year: string;
  goal: Goal | "";
  preferred_language: string;
  lessons_count: number;
  /** The later of their latest lesson activity and last sign-in; null if neither. */
  last_active_at: string | null;
  profile_complete: boolean;
  is_staff: boolean;
  joined_at: string;
};
export type LearnerSummary = { total: number; active_7d: number; profile_complete: number; staff: number };
export type LearnerPage = Page<ConsoleLearner> & { summary: LearnerSummary };

export type AuditEntry = {
  id: number;
  actor: { id: string; name: string; email: string } | null;
  actor_email: string;
  /** For example "model.update", "node.update", "run.retry". */
  action: string;
  target_type: string;
  target_id: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  /** The top-level fields that differ between before and after. */
  changed_fields: string[];
  created_at: string;
};
