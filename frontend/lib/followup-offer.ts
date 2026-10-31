import type { FollowupLevel, FollowupOffer, OfferAction, OfferKind } from "@/lib/types";

/** What the button of an offer does: make the lesson of a level, or open one that exists. */
export type OfferStep = { label: string; intent: "make"; level: FollowupLevel } | { label: string; intent: "open"; lessonId: string };

export type OfferView = {
  /** A pop-up the learner can skip, or a small note under the result. */
  surface: "dialog" | "note";
  title: string;
  message: string;
  /** Null when there is nothing to press (the note, or an offer that points at a lesson we cannot name). */
  step: OfferStep | null;
  /** The words to turn it down. */
  skip: string;
};

const KINDS: readonly OfferKind[] = ["foundation", "advanced", "inline_suggestion"];
const ACTIONS: readonly OfferAction[] = ["generate", "revisit", "open", "revisit_or_related"];

const OPEN_IT = "Open it";

/**
 * What a learner reads after a result when the server made an offer (spec 3.3). The server decides which offer; this only
 * says it. The words never tell anyone they were wrong about their own level: a pop-up is about the result, and a learner
 * who rated themselves low and did badly gets only a quiet note, not a suggestion to start somewhere else.
 */
export class FollowupOffers {
  /** The offer stored on an attempt, or null for none, or for anything that is not an offer this page knows. */
  static parse(raw: unknown): FollowupOffer | null {
    if (typeof raw !== "object" || raw === null) return null;
    const { kind, action, lesson_id: lessonId } = raw as Record<string, unknown>;
    if (!KINDS.includes(kind as OfferKind) || !ACTIONS.includes(action as OfferAction)) return null;
    return { kind: kind as OfferKind, action: action as OfferAction, lesson_id: typeof lessonId === "string" && lessonId ? lessonId : null };
  }

  static view(offer: FollowupOffer): OfferView {
    switch (offer.kind) {
      case "foundation":
        return offer.action === "generate" ? FollowupOffers.makeFoundation() : FollowupOffers.openFoundation(offer.lesson_id);
      case "advanced":
        return offer.action === "generate" ? FollowupOffers.makeAdvanced() : FollowupOffers.openAdvanced(offer.lesson_id);
      case "inline_suggestion":
        return FollowupOffers.note();
    }
  }

  private static makeFoundation(): OfferView {
    return {
      surface: "dialog",
      title: "Want to build up the basics?",
      message: "Some of this was tricky, and that's useful to know. A short Foundation lesson can build up the basics behind it, and we can make one for you now.",
      step: { label: "Make a Foundation lesson", intent: "make", level: "foundation" },
      skip: "Not now",
    };
  }

  private static openFoundation(lessonId: string | null): OfferView {
    return {
      surface: "dialog",
      title: "Your Foundation lesson is ready",
      message: "You already have a Foundation lesson for this topic. Going back through it could help this click.",
      step: lessonId ? { label: OPEN_IT, intent: "open", lessonId } : null,
      skip: "Not now",
    };
  }

  private static makeAdvanced(): OfferView {
    return {
      surface: "dialog",
      title: "Ready for more?",
      message: "You did really well. Want a lesson that goes further? We can make an Advanced one for you now.",
      step: { label: "Make an Advanced lesson", intent: "make", level: "advanced" },
      skip: "Not now",
    };
  }

  private static openAdvanced(lessonId: string | null): OfferView {
    return {
      surface: "dialog",
      title: "Your Advanced lesson is waiting",
      message: "You already have an Advanced lesson for this topic. It picks up where this one leaves off.",
      step: lessonId ? { label: OPEN_IT, intent: "open", lessonId } : null,
      skip: "Not now",
    };
  }

  private static note(): OfferView {
    return {
      surface: "note",
      title: "That one was a stretch",
      message: "Going back over the lesson can help, or you can try a related lesson from the topics below. There's no rush.",
      step: null,
      skip: "",
    };
  }
}
