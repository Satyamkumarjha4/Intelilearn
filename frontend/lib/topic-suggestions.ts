import { apiClient, type ApiClient } from "@/lib/api";

export type TopicSuggestion = { subject: string; title: string; reason: string };
export type SuggestionPage = { topics: TopicSuggestion[]; hasMore: boolean };
/** What the server needs to pick topics: the answers of steps 1 to 4 (the same ones that are saved as the profile). */
export type SuggestionAnswers = { education_level: string; goal: string; preferred_language: string; grade_or_year: string; field_of_study: string };

const PER_PAGE = 4;
const TOPIC_MAX = 200;

const text = (value: unknown): string => (typeof value === "string" ? value.trim() : "");

/**
 * First topics to start with, picked for the learner from their answers (`POST /onboarding/topic-suggestions`; pages
 * count from 0 and wrap round, so "show me others" never runs dry). The answer comes from a model, so it is read
 * defensively: a bad card is dropped, and a bad answer is an empty page.
 */
export class TopicSuggestions {
  constructor(private readonly client: ApiClient = apiClient) {}

  async page(answers: SuggestionAnswers, page: number): Promise<SuggestionPage> {
    const raw = await this.client.request<unknown>("/onboarding/topic-suggestions", { method: "POST", body: { ...answers, page } });
    const answer = raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
    const topics = (Array.isArray(answer.topics) ? answer.topics : [])
      .map((item): TopicSuggestion => {
        const card = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
        return { subject: text(card.subject), title: text(card.title), reason: text(card.reason) };
      })
      .filter((card) => card.title !== "")
      .slice(0, PER_PAGE);
    return { topics, hasMore: answer.has_more === true && topics.length > 0 };
  }
}

export const topicSuggestions = new TopicSuggestions();

/** What the learner chose to start with: a suggested card, or a topic of their own. One choice, two inputs. */
export class TopicPick {
  constructor(
    readonly selected: TopicSuggestion | null = null,
    readonly typed = "",
  ) {}

  pick(card: TopicSuggestion): TopicPick {
    return new TopicPick(card, "");
  }

  /** Typing takes the card away (typing nothing leaves it). */
  type(value: string): TopicPick {
    return value === "" ? new TopicPick(this.selected, "") : new TopicPick(null, value);
  }

  /** The topic the quick check starts on. */
  topic(): string {
    return (this.selected?.title ?? this.typed).trim().slice(0, TOPIC_MAX);
  }

  get canStart(): boolean {
    return this.selected !== null || this.typed.trim().length >= 2;
  }
}
