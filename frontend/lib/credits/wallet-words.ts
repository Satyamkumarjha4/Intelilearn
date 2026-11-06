import { ShortDate } from "./short-date";
import type { WalletBucket } from "./types";

/** One line of "your credits": credits of one kind that run out on the same day. */
export type CreditGroup = { key: string; label: string; remaining: number; expiresAt: string | null; expiry: string };

const SOURCES: Record<string, string> = {
  signup: "Welcome credits",
  daily: "Daily credits",
  weekly_streak: "Weekly streak bonus",
  monthly_streak: "Monthly streak bonus",
  purchase: "Bought credits",
  subscription: "Plan credits",
  admin_grant: "A gift from us",
  refund: "Given back",
};

const DAY_MS = 86_400_000;

/**
 * The wallet in a learner's words. A learner has credits and things cost credits; they never meet a bucket, a hold or a
 * ledger. The numbers are the server's; this only groups and names them.
 */
export class WalletWords {
  static readonly NONE = "You don't have any credits right now.";

  static source(source: string): string {
    return SOURCES[source] ?? "Credits";
  }

  /** When credits run out, in the learner's calendar. `now` is injected so the words are the same in a test. */
  static expiry(expiresAt: string | null, now: Date = new Date()): string {
    if (!expiresAt) return "Never runs out";
    const at = new Date(expiresAt);
    const days = Math.round((WalletWords.startOfDay(at) - WalletWords.startOfDay(now)) / DAY_MS);
    if (days <= 0) return "Runs out today";
    if (days === 1) return "Runs out tomorrow";
    return `Runs out on ${WalletWords.date(at)}`;
  }

  /** "Fri 14 Nov". */
  static date(at: Date): string {
    return ShortDate.of(at);
  }

  /** What is set aside while lessons are being made. */
  static reserved(count: number): string {
    return `${WalletWords.credits(count)} being used for lessons being made`;
  }

  static credits(count: number): string {
    return `${count} ${count === 1 ? "credit" : "credits"}`;
  }

  /** The server's spend order, with parcels of the same kind that run out the same day merged into one line. */
  static groups(buckets: WalletBucket[], now: Date = new Date()): CreditGroup[] {
    const groups: CreditGroup[] = [];
    for (const bucket of buckets) {
      const day = bucket.expires_at ? WalletWords.startOfDay(new Date(bucket.expires_at)) : "never";
      const key = `${bucket.source}|${day}`;
      const found = groups.find((group) => group.key === key);
      if (found) found.remaining += bucket.remaining;
      else {
        groups.push({
          key,
          label: WalletWords.source(bucket.source),
          remaining: bucket.remaining,
          expiresAt: bucket.expires_at,
          expiry: WalletWords.expiry(bucket.expires_at, now),
        });
      }
    }
    return groups;
  }

  private static startOfDay(at: Date): number {
    return new Date(at.getFullYear(), at.getMonth(), at.getDate()).getTime();
  }
}
