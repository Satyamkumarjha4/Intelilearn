export type EmailStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const KEY = "socra.pendingEmail";

/**
 * The address a sign-up code was sent to, kept in `sessionStorage` so a refresh of the "Check your email" screen still
 * knows where the code went. A convenience only (it carries no authority): with no storage or broken storage nothing here
 * ever throws, and the screen then offers to start again.
 */
export class PendingEmail {
  constructor(private readonly storage: EmailStorage | undefined = PendingEmail.browserStorage()) {}

  save(email: string): void {
    const address = email.trim();
    this.guarded(() => (address ? this.storage?.setItem(KEY, address) : this.storage?.removeItem(KEY)));
  }

  peek(): string | null {
    return this.guarded(() => this.storage?.getItem(KEY)) ?? null;
  }

  clear(): void {
    this.guarded(() => this.storage?.removeItem(KEY));
  }

  private guarded<T>(action: () => T): T | undefined {
    try {
      return action();
    } catch {
      return undefined;
    }
  }

  private static browserStorage(): EmailStorage | undefined {
    try {
      return typeof window === "undefined" ? undefined : window.sessionStorage;
    } catch {
      return undefined;
    }
  }
}
