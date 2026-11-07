/**
 * Unit under test: `ConsolePaymentWords`, how the payments board and the revenue block read for staff.
 *
 * Why: a state read wrongly (a paid order that was not given its credits shown as done) sends support the wrong way, and
 * a sign lost on a negative net hides a loss. Money must read in rupees, to the paisa when it has one.
 *
 * Use cases:
 * - every order state and every refund state has a label and a tone, and "paid, not yet given" is a warning, not done
 * - paise read as rupees: whole rupees without decimals, others to the paisa, with Indian digit grouping
 * - the API's rupee strings keep their sign (a real minus), always two decimals
 * - what is left to refund is only for a fulfilled order, never below zero
 * - the refund line says how much and what the provider said; the rate note names the rate used
 */
import { describe, expect, test } from "bun:test";

import { ConsolePaymentWords as Words } from "./payment-words";

describe("ConsolePaymentWords", () => {
  test("every state has words and a tone, and a payment taken but not given is a warning", () => {
    expect(Object.keys(Words.STATUS).sort()).toEqual(["created", "expired", "failed", "fulfilled", "paid", "pending"]);
    expect(Words.STATUS.paid.tone).toBe("warn");
    expect(Words.STATUS.fulfilled).toEqual({ label: "Credits given", tone: "ok" });
    expect(Object.keys(Words.REFUND).sort()).toEqual(["confirmed", "failed", "pending"]);
    expect(Words.REFUND.failed.tone).toBe("bad");
  });

  test.each([[49900, "₹499"], [1250, "₹12.50"], [123456700, "₹12,34,567"], [5, "₹0.05"], [0, "₹0"]])("%i paise reads %s", (paise, text) => {
    expect(Words.paise(paise)).toBe(text);
  });

  test("a rupee string keeps its sign and two decimals", () => {
    expect(Words.rupees("350.00")).toBe("₹350.00");
    expect(Words.rupees("-40.00")).toBe("−₹40.00");
    expect(Words.rupees("1234567.50")).toBe("₹12,34,567.50");
    expect(Words.rupees("0.00")).toBe("₹0.00");
  });

  test("only a fulfilled order can be refunded, for what is left", () => {
    expect(Words.refundable({ status: "fulfilled", amount_paise: 10000, refunded_paise: 2500 })).toBe(7500);
    expect(Words.refundable({ status: "fulfilled", amount_paise: 10000, refunded_paise: 10000 })).toBe(0);
    expect(Words.refundable({ status: "pending", amount_paise: 10000, refunded_paise: 0 })).toBe(0);
    expect(Words.refundable({ status: "fulfilled", amount_paise: 100, refunded_paise: 500 })).toBe(0);
  });

  test("the refund line and the rate note", () => {
    const refund = { id: 1, amount_paise: 4000, refund_ref: "re_1", state: "pending", created_at: "x", resolved_at: null, can_mark_failed: false } as const;

    expect(Words.refundLine(refund)).toBe("₹40 · Waiting for the provider");
    expect(Words.rate({ usd_inr_rate: "85" })).toBe("Model cost is recorded in dollars and shown at ₹85 to the dollar.");
  });
});
