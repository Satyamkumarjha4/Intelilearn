/**
 * Unit under test: `RoutingView`, the words and marks of the Model routing page.
 *
 * Why: the page is read at a glance ("which model does this step use first, and what happens if it fails?"). A chip
 * that shows a parked model like a live one, a caption that numbers the fallback wrongly, or a step that says it is
 * "off" while it is only set to no reasoning, would make the staff change the wrong thing. The selected step lives
 * in the address, and an address names whatever it likes, so an unknown step must not open an empty editor.
 *
 * Use cases:
 * - names a phase for its heading
 * - writes a step's effort chip, or "off" when the step is off
 * - shows the chain as chips: the model's name, its provider's fixed colour, and whether it is parked
 * - captions each place in the chain ("Tried first", "Used if #1 fails")
 * - writes a model's price per million output tokens, or says there is none
 * - says why a required step cannot be switched off
 * - reads the selected step from the address (only a step that exists) and writes it back
 */
import { describe, expect, test } from "bun:test";

import { RoutingView } from "./routing-view";
import type { ConsoleModel, NodeRouting } from "./types";

const node = (extra: Partial<NodeRouting> = {}): NodeRouting =>
  ({
    key: "lesson.plan",
    phase: "author",
    enabled: true,
    optional: false,
    reasoning_effort: "high",
    bindings: [
      { model: 1, model_label: "groq/gpt-oss-120b", enabled: true },
      { model: 2, model_label: "gemini/gemini-3.5-flash", enabled: false },
      { model: null, model_label: "mystery/x", enabled: true },
    ],
    ...extra,
  }) as NodeRouting;

describe("phase", () => {
  test.each([
    ["diagnose", "Diagnose"],
    ["author", "Author"],
    ["build", "Build"],
    ["post", "After"],
    ["onboarding", "Onboarding"],
  ] as const)("%s reads %s", (phase, label) => {
    expect(RoutingView.phase(phase)).toBe(label);
  });
});

describe("effort", () => {
  test("is the effort in words, or off when the step is off", () => {
    expect(RoutingView.effort(node())).toBe("high effort");
    expect(RoutingView.effort(node({ reasoning_effort: "none" }))).toBe("no reasoning");
    expect(RoutingView.effort(node({ enabled: false }))).toBe("off");
  });
});

describe("chain", () => {
  test("shows the model's name without its provider, in the provider's fixed colour series", () => {
    const [first, second, third] = RoutingView.chain(node());

    expect(first).toMatchObject({ name: "gpt-oss-120b", full: "groq/gpt-oss-120b", series: "groq", parked: false });
    expect(second).toMatchObject({ name: "gemini-3.5-flash", series: "google", parked: true });
    expect(third).toMatchObject({ name: "x", series: "other" });
  });
});

describe("caption", () => {
  test("says what each place in the chain is for", () => {
    expect(RoutingView.caption(0)).toBe("Tried first");
    expect(RoutingView.caption(1)).toBe("Used if #1 fails");
    expect(RoutingView.caption(3)).toBe("Used if #3 fails");
  });
});

describe("price", () => {
  const model = (out: string | null) => ({ output_cost_per_mtok: out }) as ConsoleModel;

  test("is dollars per million output tokens", () => {
    expect(RoutingView.price(model("0.6000"))).toBe("$0.60/M out");
    expect(RoutingView.price(model("2.5"))).toBe("$2.50/M out");
    expect(RoutingView.price(model("0"))).toBe("free");
  });

  test("says when there is none to show", () => {
    expect(RoutingView.price(model(null))).toBe("price not set");
    expect(RoutingView.price(undefined)).toBe("price unknown");
  });
});

describe("requiredReason", () => {
  test("a required step says why it cannot be switched off; an optional one says nothing", () => {
    expect(RoutingView.requiredReason(node())).toBe("Required step: lessons cannot build without it.");
    expect(RoutingView.requiredReason(node({ optional: true }))).toBeNull();
  });
});

describe("selection", () => {
  const keys = ["a.one", "b.two"];

  test("is the step in the address, only when it exists", () => {
    expect(RoutingView.selected(new URLSearchParams("node=b.two"), keys)).toBe("b.two");
    expect(RoutingView.selected(new URLSearchParams("node=nope"), keys)).toBeNull();
    expect(RoutingView.selected(new URLSearchParams(""), keys)).toBeNull();
  });

  test("is written back to the address", () => {
    expect(RoutingView.href("/console/routing", "b.two")).toBe("/console/routing?node=b.two");
    expect(RoutingView.href("/console/routing", null)).toBe("/console/routing");
  });
});
