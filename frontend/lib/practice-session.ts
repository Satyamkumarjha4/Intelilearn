import type { PracticeGrade, PracticeQuestion } from "@/lib/types";

type GradeOf = PracticeGrade["results"][number];

/** A learner's work on a practice sheet. Nothing is stored on the server, so this is the record. */
export class PracticeSession {
  private readonly answers = new Map<string, number | string>();
  private readonly shown = new Set<string>();
  private grades = new Map<string, GradeOf>();
  score: PracticeGrade["score"] | null = null;

  constructor(readonly questions: PracticeQuestion[]) {}

  get answered(): number {
    return this.answers.size;
  }

  get revealed(): string[] {
    return [...this.shown];
  }

  answerOf(id: string): number | string | undefined {
    return this.answers.get(id);
  }

  /** A multiple-choice answer is an option index; anything typed is text, and a blank answer is no answer. */
  setAnswer(id: string, value: number | string): void {
    if (typeof value === "string" && value.trim() === "") this.answers.delete(id);
    else this.answers.set(id, value);
  }

  payload(): Record<string, number | string> {
    return Object.fromEntries([...this.answers].map(([id, value]) => [id, typeof value === "string" ? value.trim() : value]));
  }

  reveal(id: string): void {
    this.shown.add(id);
  }

  isRevealed(id: string): boolean {
    return this.shown.has(id);
  }

  mark(grade: PracticeGrade): void {
    this.grades = new Map(grade.results.map((result) => [result.id, result]));
    this.score = grade.score;
  }

  gradeOf(id: string): GradeOf | undefined {
    return this.grades.get(id);
  }

  reset(): void {
    this.answers.clear();
    this.shown.clear();
    this.grades = new Map();
    this.score = null;
  }
}
