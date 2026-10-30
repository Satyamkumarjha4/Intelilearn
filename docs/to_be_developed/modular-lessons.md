# Feature Spec: Modular Lesson Parts

**Product:** Socra
**Status:** Finalized design, ready for implementation
**Last updated:** 2026-10-30 (amended: see the changelog in [modular-lessons-implementation-plan.md](modular-lessons-implementation-plan.md#spec-amendments))

---

## 1. Overview

Today Socra has a single pipeline: diagnostic → lesson → final test → (only on 10/10) cheat sheet / revision sheet.

This feature breaks that pipeline into independent parts that a learner can use on their own or together:

- **Full lesson**: with a choice of diagnostic quiz or self-rating.
- **Quick quiz**: standalone, configurable, from a new topic or from one or more existing lessons.
- **Cheat sheet / revision sheet**: standalone, from a topic or from an existing lesson.
- **Retest**: retry a lesson's final test with new questions.
- **Follow-up lessons**: Foundation or Advanced lessons suggested when a test result contradicts the learner's expected level.

The 10/10 gate on cheat sheets and revision sheets is removed. They are available any time. A perfect score on the diagnostic quiz shows a choice: continue with an Expert lesson, or get the cheat sheet and revision sheet only.

---

## 2. Core Concepts

### 2.1 LearnerProfile

Every generator (lesson, test, quiz, sheets) consumes a single `LearnerProfile` object. Generators do not care how it was produced.

| Source | What it provides |
|---|---|
| Diagnostic quiz | Level + known / weak concepts |
| Self-rating (stars) | Level only |
| Calibration quiz (quick quiz flow) | Level only |
| Existing test score | Level (per lesson) |

### 2.2 Levels

Self-rating is 0.5–5 stars (half-star steps). Each star value shows explanatory text when selected, describing what that rating means. The approved sentences:

| Stars | Sentence |
|---|---|
| 0.5 | "This is completely new to me." |
| 1 | "I've heard the name, but I don't know what it means." |
| 1.5 | "I have a rough idea what it is, but I couldn't explain it." |
| 2 | "I know a few words and ideas, but I get lost quickly." |
| 2.5 | "I understand some of the basics, but I need help to use them." |
| 3 | "I know the basics and can solve simple problems." |
| 3.5 | "I can solve most simple problems and I am starting on harder ones." |
| 4 | "I am comfortable with it and can solve most problems on my own." |
| 4.5 | "I can solve hard problems and spot my own mistakes." |
| 5 | "I could explain it to someone else." |

| Rating | Level | Lesson shape |
|---|---|---|
| 0.5 – 1.5 | Beginner | Prerequisites → Intro → Core |
| 2 – 3.5 | Foundation | Intro → Core → light Advanced |
| 4 | Proficient | Quick recap → Core → Advanced |
| 4.5 – 5 | Expert | Core as page 1 → Advanced → Expert depth |

When the diagnostic quiz is used instead of a self-rating, the level assigned by the diagnostic is used in place of the star rating everywhere in this spec.

**Rater categories** (used by the pop-up rules in §3.3):

- **Low rater:** rating ≤ 1.5
- **High rater:** rating ≥ 4.5
- **Mid rater:** everything in between

---

## 3. Full Lesson Flow

### 3.1 Entry

1. User enters a topic.
2. User picks one option on a toggle:
   - **Take the diagnostic quiz.** Produces a rich `LearnerProfile`.
   - **Rate yourself.** 0.5–5 stars, with explanatory text.
3. Lesson is generated using the level → lesson shape mapping (§2.2).
4. User studies the lesson (revisitable any number of times).
5. User takes the final test: **10 questions, objective only (MCQ, MSQ, numerical), 2 per difficulty level**, for every lesson level. It is graded in full when submitted.

### 3.2 Test result bands

| Score | Band |
|---|---|
| < 30% | **Fail** |
| 30% – 90% | **Normal** |
| > 90% | **Excellent** |

Standard recommendations are generated after every test, as today. The pop-ups below are *in addition* to those recommendations.

### 3.3 Post-test pop-ups

Pop-ups appear **only when the result contradicts the expected level**. Socra should not tell users they are wrong when they rated themselves correctly. All pop-ups are skippable.

#### Foundation pop-up (on Fail)

- Shown on **every failed attempt** until the user has passed (scored ≥ 30%) on this lesson **at least once**. After the first pass, it is never shown again for this lesson, even if later attempts fail.
- If a Foundation lesson for this lesson **does not exist**: offer to generate one.
- If it **already exists**: suggest revisiting it (do not generate a second one).
- **Not shown to low raters.** A low rater who fails rated themselves correctly. Show an inline suggestion instead: revisit the lesson, or try a related lesson.

#### Advanced pop-up (on Excellent)

- Shown on **any attempt scoring > 90%**, including after earlier fails.
- If an Advanced lesson for this lesson **does not exist**: offer to generate one.
- If it **already exists**: point the user to it.
- **Not shown to high raters.** A high rater who excels rated themselves correctly.

#### Cross cases (always get the pop-up)

- A low rater who scores > 90% gets the **Advanced** pop-up.
- A high rater who scores < 30% gets the **Foundation** pop-up.

#### Pseudocode

```python
def post_test_popup(lesson, attempt, rater_category):
    band = score_band(attempt.score_pct)  # FAIL / NORMAL / EXCELLENT

    if band == FAIL:
        if rater_category == LOW:
            return InlineSuggestion("revisit_lesson_or_related")
        if lesson.has_passed_once():  # any attempt with score >= 30%
            return None
        foundation = lesson.followup(level="foundation")
        return Popup("foundation", action="revisit" if foundation else "generate")

    if band == EXCELLENT:
        if rater_category == HIGH:
            return None
        advanced = lesson.followup(level="advanced")
        return Popup("advanced", action="open" if advanced else "generate")

    return None  # NORMAL band: no pop-up
```

#### Worked examples

| Rating | Attempts | Pop-ups |
|---|---|---|
| Mid (3) | Fail → Fail → Pass → Fail → Excellent | Foundation (generate) → Foundation (revisit) → none → none (passed once) → Advanced |
| Mid (3) | Normal → Fail → Excellent | none → none (passed once) → Advanced |
| Low (1) | Fail → Fail | inline suggestion → inline suggestion |
| Low (1) | Excellent | Advanced (cross case) |
| High (5) | Excellent | none |
| High (4.5) | Fail | Foundation (cross case) |

### 3.4 Follow-up lessons (Foundation / Advanced)

- A follow-up is a **separate, independent lesson**, not a child of the original.
- **Level-specific name**, generated by the model:
  - Foundation: e.g. "Foundations of Trigonometry", "Introduction to Trigonometry"
  - Advanced: e.g. "Advanced Trigonometry", "Mastering Trigonometry"
- **Linked by metadata only:** `created_from_lesson_id` and `followup_level` (foundation / advanced). This enables the "already exists" checks above and future learning-path views.
- **No self-rating step.** The level is derived from the test score that triggered it.
- **Name collision:** if the user already has a lesson with the generated name, reuse that lesson or add a suffix. Never create a confusing duplicate.
- Per-concept targeting is **out of scope**. The follow-up uses the overall score only (keep it simple).

---

## 4. Retest

- A lesson's final test can be retaken **any number of times**.
- Each attempt gets a **new set of questions**.
- Each attempt is **immutable and read-only** once submitted.
- Results show improvement or decline across attempts: score trend, delta vs the previous attempt and vs the best attempt, time taken.
- The pop-up rules in §3.3 run after every attempt.

**Question variety:** every retake generates a **fresh 10-question set** through the same pipeline as the first attempt, following the same fixed blueprint so attempts stay comparable. The generator is given every question the lesson has already asked and must not repeat them (plan D20).

---

## 5. Quick Quiz

A **separate LangGraph flow** with its own graph. It must **share** the question-generation and grading node implementations with the final test, so the two never drift apart.

### 5.1 Flow

1. **Source**
   - **New topic**, or
   - **Existing lessons**: select one or more lessons to combine (**at most 10**).
2. **Number of questions**: a preset of 5, 10, 15, 20, 25 or 30 (default 10).
3. **Question types** (multi-select): MCQ, MSQ, Numerical, Short answer, Long answer.
   - Code questions fall under Short (small code) and Long (larger code).
   - Only **topic-relevant types** are shown (e.g. no code for history, no numerical for literature).
   - **Short and long answers are only available for quizzes of 10 or more questions.** The calibration quiz is MCQ only.
4. **Level** (inferred as the default, user can override):
   - **Self-rating** (stars), or
   - **Calibration quiz**: 5 questions, **adaptive**, MCQ-only. Start at standard; go harder after a correct answer and easier after a wrong one. Output: a level.
   - **Existing test score**: when the source is completed lessons, use that lesson's test score. With multiple lessons, each lesson's questions use that lesson's own level.
5. **Generate** the quiz.
6. **Take** the quiz (same one-question-at-a-time, forward-only UX as the final test).
7. **Results + recommendations**:
   - Lesson-sourced quiz: "study this" recommendations with **deep links to the lesson page** covering each weak concept. This requires lesson pages to carry concept tags, added at generation time.
   - Topic-sourced quiz: offer "Create a lesson for this", reusing the quiz result as the `LearnerProfile`.

Quick quizzes can be retaken. Each retake gets new questions, and attempts are compared only when they use the same configuration.

### 5.2 Generation notes

- **Never generate all questions in one LLM call.** Fan out in parallel batches of about 5–10 (LangGraph `Send`), then deduplicate.
- **Multi-lesson source:** feed per-lesson **concept summaries** (stored at lesson generation time), not full lesson text, within a token budget per source, and split the questions evenly across the selected lessons, with any remainder going to the most recent lessons. The question count must be at least the number of lessons.

---

## 6. Marking Scheme

General rules:

- **Integer marks only.** Never fractions.
- **Partial credit** where defined.
- **No negative marking.** An incorrect answer scores 0 at worst.
- Percentages are computed from marks, not question counts.

### 6.1 Marks per question

There are five difficulty levels: **Easy, Basic, Standard, Difficult, Expert**. The Normal column covers Easy, Basic and Standard. "Difficult" means questions at the **Difficult** or **Expert** levels.

| Type | Normal | Difficult / Expert |
|---|---|---|
| MCQ | 1 | 2 |
| MSQ | 2 | 3 |
| Numerical | 2 | 3 |
| Short answer | 2 | 3 |
| Long answer | 5 | 6 |

Numerical base marks are confirmed: 2 normal, 3 difficult / expert (matching MSQ).

### 6.2 MCQ

Correct answer scores full marks. Anything else scores 0.

### 6.3 MSQ (multiple select)

- Every MSQ has **at least two** correct options.
- Scoring, evaluated in order:

| Selection | Marks |
|---|---|
| Nothing selected | 0 |
| Any wrong option selected | 0 |
| All correct options, no wrong ones | Full |
| ≥ 50% of correct options, no wrong ones | Full − 1 |
| ≥ 1 but < 50% of correct options, no wrong ones | 1 |

Resulting scales:

- 2-mark MSQ: 2 / 1 / 1 / 0
- 3-mark MSQ: 3 / 2 / 1 / 0

### 6.4 Numerical

- Each question defines:
  - `tolerance`: answers within the range score full marks; outside it, 0.
  - `decimal_precision`: how many decimal places are accepted (or integer-only).
- Units are stated in the question text. The input field accepts a number only.
- **Answer key reliability:** the generator outputs the answer as an **expression** (e.g. `sqrt(3)/2 * 10`), and the backend **computes** it with a small `ast`-based `ExpressionEvaluator` (a whitelist of operators, functions and constants; never `eval`, never `sympy`'s parser). Never trust a number typed by the LLM.

### 6.5 Short and long answers (including code)

- Graded by an LLM against a **rubric generated with the question**: a model answer plus point-valued criteria (e.g. "mentions X: 1 mark; explains Y: 2 marks").
- The grader awards marks criterion by criterion, so partial credit is consistent and always an integer.
- Each answer gets written feedback.
- Results are labeled **"AI-graded"**.
- **Code is not executed.** There is no sandbox; code is checked by the LLM against the rubric.
- Code answers use a proper code editor in the UI (CodeMirror or Monaco).

---

## 7. Cheat Sheet & Revision Sheet

- **Cheat sheet:** a compact one-glance reference (key terms, formulas, rules).
- **Revision sheet:** recall-oriented: key points, self-check prompts, common mistakes.

Generation options:

- **From a topic:** the user picks the diagnostic quiz or a self-rating (same toggle as the full lesson), then picks one or both sheets. Both sheets are generated from the same `LearnerProfile`, so the quiz or rating happens once.
- **From an existing lesson:** grounded in the lesson content (highest quality).

Each sheet is generated **once per kind** for a lesson; asking again for one that exists opens it. There are no versions.

The 10/10 gate is removed. Sheets are available from any ready lesson. A perfect score on the diagnostic quiz shows a choice between continuing with an Expert lesson and getting the cheat sheet and revision sheet only (anything else attached to a perfect score is specified separately).

---

## 8. Proposed Data Model (sketch)

```
Topic
  └─ Lesson
       ├─ level, source (diagnostic | self_rating | test_score), self_rating
       ├─ created_from_lesson_id (nullable), followup_level (foundation | advanced | null)
       ├─ concept_summary (for multi-lesson quizzes)
       ├─ pages[] (each with concept tags)
       ├─ DiagnosticQuiz (one-time, read-only after completion)
       ├─ Question[] (the record of every question asked; concept, difficulty, type, marks, rubric / answer_expr / tolerance / decimal_precision)
       ├─ TestAttempt[] (immutable; score, marks, per-question results, popup_shown)
       └─ Sheet[] (type: cheat | revision)

QuickQuiz
  ├─ source_type (topic | lessons), source_lesson_ids[], topic
  ├─ config (num_questions, types[], level, level_source)
  └─ QuickQuizAttempt[] (immutable)

LearnerProfile (value object, not necessarily persisted on its own)
  └─ level, known_concepts[], weak_concepts[], source
```

---

## 9. LangGraph Structure

- **Shared nodes:**
  - question generation, per type
  - grading:
    - deterministic: MCQ, MSQ, numerical
    - LLM: short, long
  - dedup
  - recommendation
- **Lesson graph:** profile (diagnostic or self-rating) → lesson generation → test.
- **Quick quiz graph:** source resolution → level resolution (rating / calibration / existing score) → parallel question generation → assemble → grade → recommend.
- **Sheet graph:** source resolution → profile → cheat and/or revision generation (in parallel when both are requested).

---

## 10. Open Questions

- [x] **Numerical base marks.** Confirmed: 2 (Difficult / Expert: 3).

## 11. Out of Scope (for now)

- Per-concept targeting for follow-up lessons
- Code execution / sandboxed test cases
- Negative marking