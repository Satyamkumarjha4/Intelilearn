import { ApiError, type FieldErrors } from "@/lib/api";

const GENERIC = "That did not work. Check the connection and try again.";

/** A failed console request as words: one sentence, and the API's messages per field when it gave them. */
export class ConsoleFailure {
  private constructor(
    readonly message: string,
    readonly fields: FieldErrors,
  ) {}

  static of(error: unknown): ConsoleFailure {
    if (!(error instanceof ApiError)) return new ConsoleFailure(GENERIC, {});
    if (error.status === 404) return new ConsoleFailure("That is not there any more. Reload the page and try again.", {});
    if (error.status === 429) {
      const wait = error.retryAfter ? `${error.retryAfter} seconds` : "a moment";
      return new ConsoleFailure(`Too many requests in a row. Try again in ${wait}.`, {});
    }
    return new ConsoleFailure(error.message, error.fields);
  }

  /**
   * Every message as a line. A field with a readable name in `labels` reads "Name: message"; one without (the chain of
   * models, whose messages already say which model) is the message as it is. With no field messages: the sentence.
   */
  lines(labels: Record<string, string>): string[] {
    const found = Object.entries(this.fields).flatMap(([field, messages]) =>
      messages.map((text) => (labels[field] ? `${labels[field]}: ${text}` : text)),
    );
    return found.length ? found : [this.message];
  }
}
