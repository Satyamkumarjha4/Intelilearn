/**
 * Unit under test: `GatewayChoices`, whether the buy page asks which way to pay.
 *
 * Why: with one way to pay there is nothing to choose and a picker is clutter; with none, buying is closed; with two or more
 * the learner picks, starting from the default. What the page sends must follow: nothing when there was no choice to make.
 *
 * Use cases:
 * - none on: buying is not open, no picker; one on: open, no picker; two or more: open, with a picker
 * - the first choice is the default when it is on, else the first listed, else none
 * - the request names a gateway only when a picker was shown, and only the one picked
 * - a key is looked up for its words
 */
import { describe, expect, test } from "bun:test";

import { GatewayChoices } from "./gateway-choices";
import type { Gateways } from "./types";

const stripe = { key: "stripe", display_name: "Card and UPI" };
const razorpay = { key: "razorpay", display_name: "Razorpay" };
const none: Gateways = { gateways: [], default: null };
const one: Gateways = { gateways: [stripe], default: "stripe" };
const two: Gateways = { gateways: [stripe, razorpay], default: "razorpay" };

describe("the picker", () => {
  test("is shown only for two or more, and buying is open for one or more", () => {
    expect([none, one, two].map((g) => [GatewayChoices.open(g), GatewayChoices.showPicker(g)])).toEqual([
      [false, false],
      [true, false],
      [true, true],
    ]);
  });
});

describe("the first choice", () => {
  test("is the default when it is on", () => {
    expect(GatewayChoices.initial(two)).toBe("razorpay");
  });

  test("is the first listed when the default is not on, and none when nothing is", () => {
    expect(GatewayChoices.initial({ gateways: [stripe, razorpay], default: "paypal" })).toBe("stripe");
    expect(GatewayChoices.initial({ gateways: [stripe], default: null })).toBe("stripe");
    expect(GatewayChoices.initial(none)).toBeNull();
  });
});

describe("the request", () => {
  test("names no gateway when there was no choice", () => {
    expect(GatewayChoices.request(one, "stripe")).toBeUndefined();
    expect(GatewayChoices.request(none, null)).toBeUndefined();
  });

  test("names the one picked when there was", () => {
    expect(GatewayChoices.request(two, "stripe")).toBe("stripe");
    expect(GatewayChoices.request(two, null)).toBeUndefined();
  });

  test("a key is looked up for its words", () => {
    expect(GatewayChoices.label(two, "stripe")?.display_name).toBe("Card and UPI");
    expect(GatewayChoices.label(two, "paypal")).toBeUndefined();
  });
});
