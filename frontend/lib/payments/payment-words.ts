import { ApiError } from "@/lib/api";
import { WalletWords } from "@/lib/credits/wallet-words";

import type { Order } from "./types";

/** What a payment says to a learner. Never a state name, a gateway's word, or a status code. */
export class PaymentWords {
  static readonly TRY_AGAIN = "We couldn't start that payment. Nothing was charged. Please try again.";

  /** Why a payment could not start, in words, from the server's own message when it wrote one for a person. */
  static refusal(error: unknown): string {
    if (!(error instanceof ApiError)) return PaymentWords.TRY_AGAIN;
    switch (error.code) {
      case "too_many_pending":
        return "You have payments that are still being confirmed. Wait for them to finish, then try again.";
      case "queue_full":
        return "You already have as many plans lined up as you can. Try again once some have run.";
      case "gateway_unavailable":
        return "We couldn't reach the payment service. Nothing was charged. Please try again in a moment.";
      case "gateway_not_enabled":
        return "That way of paying isn't available. Pick another.";
      case "invalid_amount":
      case "invalid_plan":
        return error.message.trim() || "That can't be bought. Check what you picked and try again.";
      default:
        return error.status === 429 ? "That's a lot of tries. Wait a moment, then try again." : PaymentWords.TRY_AGAIN;
    }
  }

  static headline(order: Order | null, phase: "waiting" | "slow" | "done" | "failed"): string {
    switch (phase) {
      case "done":
        return "Your credits are here";
      case "failed":
        return order?.status === "expired" ? "That payment timed out" : "That payment didn't go through";
      case "slow":
        return "Still confirming your payment";
      default:
        return "Confirming your payment";
    }
  }

  static detail(order: Order | null, phase: "waiting" | "slow" | "done" | "failed", cancelled: boolean): string {
    switch (phase) {
      case "done":
        if (!order) return "";
        if (order.plan.key === "one_time") return `${WalletWords.credits(order.credits)} ${order.credits === 1 ? "was" : "were"} added.`;
        return `${order.plan.name} has started. Its credits come a period at a time, and the first ones are in your wallet now.`;
      case "failed":
        return "Nothing was charged. If you were charged, your credits will still arrive: we check with the payment service.";
      case "slow":
        return "This is taking longer than usual. You can leave this page: your credits will be added as soon as the payment is confirmed.";
      default:
        return cancelled ? "If you changed your mind, you can head back. If you paid, this will update in a moment." : "This usually takes a few seconds. Please keep this page open.";
    }
  }
}
