import type { User } from "@/lib/types";

export type AccessState = "checking" | "signed-out" | "denied" | "allowed";

/**
 * Who may see the console, and what its layout does about it. The API is what really decides (it answers anyone who is
 * not staff with a 404); this keeps the page from flashing and from announcing itself: a learner gets the same
 * not-found page as for any address that does not exist, not a "forbidden".
 */
export class ConsoleGate {
  static decide({ loading, user }: { loading: boolean; user: Pick<User, "is_staff"> | null }): AccessState {
    if (loading) return "checking";
    if (!user) return "signed-out";
    return user.is_staff ? "allowed" : "denied";
  }

  /** Where to sign in so that the visitor comes back to this page, filters included. */
  static signInHref(pathname: string, search: string): string {
    return `/auth?next=${encodeURIComponent(pathname + search)}`;
  }

  /** Whether the learner app's account menu offers a Console link. */
  static offeredTo(user: Pick<User, "is_staff"> | null | undefined): boolean {
    return user?.is_staff === true;
  }
}
