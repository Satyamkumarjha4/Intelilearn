/** The letters in a person's round avatar. */
export class Initials {
  static of(person: { name: string; email: string } | null | undefined): string {
    const fromName = (person?.name ?? "")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join("");
    return fromName || (person?.email ?? "").trim().charAt(0).toUpperCase() || "?";
  }
}
