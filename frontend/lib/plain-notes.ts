const RULES: [RegExp, string][] = [
  [/quiz review was skipped/i, "We skipped a second look at your quick check questions."],
  [/quiz reviewer still had concerns/i, "A second look at your quick check flagged a few questions, so one or two may be a little off."],
  [/could not be checked by the vision/i, "We couldn't double-check one of the pictures, so it's shown as we found it."],
  [/standard layout/i, "We used a simpler layout for one of the pages."],
  [/dropped the interactive/i, "We left out one interactive that wouldn't work properly."],
  [/interactive plan kept/i, "We trimmed a few planned interactives that didn't pass our checks."],
  [/no suitable .* found/i, "We couldn't find a good picture for one spot, so we drew a diagram instead."],
  [/could not find better media/i, "We couldn't find a better picture for one spot."],
  [/was kept despite/i, "One part of the lesson didn't fully pass our checks, so it may read a little roughly."],
  [/could not apply the review fix/i, "A suggested fix couldn't be applied, so that part stays as first written."],
];

const ERROR_RULES: [RegExp, string][] = [
  [/cancel|stopped/i, "Building was stopped before it finished. Retry picks it up where it left off."],
  [/queue|worker|broker/i, "Our helper isn't answering at the moment. Try again in a minute."],
  [/sandbox|render|code checks|layout|browser/i, "The lesson didn't pass our quality checks this time. Trying again often fixes it."],
  [/\bAI\b|model|provider|rate limit|quota|429|timeout|timed out|overloaded|not set up/i, "Our writing helper is busy or unavailable right now. Trying again in a few minutes usually works."],
];

/** Why a lesson failed, without the machinery: the stored reason is written for developers. */
export class PlainError {
  static readonly FALLBACK = "Something went wrong on our side. Nothing you did caused it.";

  static of(message: string): string {
    return ERROR_RULES.find(([pattern]) => pattern.test(message))?.[1] ?? PlainError.FALLBACK;
  }
}

/** The notes the lesson builder leaves are written for developers; this says them the way a learner would. */
export class PlainWarning {
  static readonly FALLBACK = "One small thing needed a workaround.";

  static of(message: string): string {
    return RULES.find(([pattern]) => pattern.test(message))?.[1] ?? PlainWarning.FALLBACK;
  }

  /** Every note in plain words, each sentence once. */
  static all(messages: string[]): string[] {
    return [...new Set(messages.map(PlainWarning.of))];
  }
}

/** Why an earlier version of a lesson was kept. The stored reason can hold the page's own error text. */
export class PlainVersion {
  static readonly FALLBACK = "An earlier version";

  static of(reason: string): string {
    if (/^runtime repair/i.test(reason)) return "Fixed a glitch on a page";
    const back = /^before going back to version (\d+)$/i.exec(reason.trim());
    return back ? `Saved before going back to version ${back[1]}` : PlainVersion.FALLBACK;
  }
}
