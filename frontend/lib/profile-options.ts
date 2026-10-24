import type { EducationLevel, Goal, LearningPreference } from "./types";

// Labels for the choices defined on accounts.models.Profile; keep the keys in sync with the backend.

export const EDUCATION_LEVELS: Record<EducationLevel, string> = {
  school: "School",
  undergraduate: "Undergraduate",
  postgraduate: "Postgraduate",
  professional: "Working professional",
  self_learner: "Self-learner",
};

export const LEARNING_PREFERENCES: Record<LearningPreference, string> = {
  visual: "Visual: diagrams, graphs, animations",
  reading: "Reading: clear written explanations",
  hands_on: "Hands-on: try things and practise",
  mixed: "A mix of everything",
};

export const GOALS: Record<Goal, string> = {
  exam_prep: "Prepare for an exam",
  deep_understanding: "Understand topics deeply",
  quick_overview: "Get a quick overview",
  interview_prep: "Prepare for interviews",
};

export const LANGUAGES: Record<string, string> = {
  en: "English",
  hi: "Hindi",
  es: "Spanish",
  fr: "French",
  de: "German",
};
