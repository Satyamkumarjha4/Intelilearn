import type { StatusTone } from "@/components/console/status-pill";

import type { PaymentRow, PaymentStatus, RefundRow, Revenue } from "./types";

/** Staff's words for the payments board: states as a tone and a label, and money as rupees. */
export class ConsolePaymentWords {
  static readonly STATUS: Record<PaymentStatus, { label: string; tone: StatusTone }> = {
    created: { label: "Started", tone: "wait" },
    pending: { label: "Waiting for payment", tone: "wait" },
    paid: { label: "Paid, not yet given", tone: "warn" },
    fulfilled: { label: "Credits given", tone: "ok" },
    failed: { label: "Failed", tone: "bad" },
    expired: { label: "Timed out", tone: "off" },
  };
  static readonly REFUND: Record<RefundRow["state"], { label: string; tone: StatusTone }> = {
    pending: { label: "Waiting for the provider", tone: "wait" },
    confirmed: { label: "Done", tone: "ok" },
    failed: { label: "Failed", tone: "bad" },
  };

  /** "₹499" for whole rupees, "₹12.50" otherwise, with Indian digit grouping. */
  static paise(paise: number): string {
    const rupees = paise / 100;
    const digits = Number.isInteger(rupees) ? 0 : 2;
    return `₹${new Intl.NumberFormat("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: 2 }).format(rupees)}`;
  }

  /** A decimal string of rupees from the API ("350.00", "-40.00") shown with its sign in front of the rupee mark. */
  static rupees(text: string): string {
    const negative = text.startsWith("-");
    const value = Number(negative ? text.slice(1) : text);
    return `${negative ? "−" : ""}₹${new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)}`;
  }

  /** What is left to refund on an order, in paise (never below 0). */
  static refundable(order: Pick<PaymentRow, "amount_paise" | "refunded_paise" | "status">): number {
    return order.status === "fulfilled" ? Math.max(0, order.amount_paise - order.refunded_paise) : 0;
  }

  /** The refund line: how much, and what the provider has said. */
  static refundLine(refund: RefundRow): string {
    return `${ConsolePaymentWords.paise(refund.amount_paise)} · ${ConsolePaymentWords.REFUND[refund.state].label}`;
  }

  /** The revenue block's rate note: which rupees-per-dollar made the model cost in rupees. */
  static rate(revenue: Pick<Revenue, "usd_inr_rate">): string {
    return `Model cost is recorded in dollars and shown at ₹${revenue.usd_inr_rate} to the dollar.`;
  }
}
