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
