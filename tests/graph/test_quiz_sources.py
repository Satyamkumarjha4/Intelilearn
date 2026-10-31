"""Unit under test: `graph.quiz_sources` (`SourceSplit`, `ConceptSummaries`, `ConceptSummary`, `TokenEstimate`): what a
quick quiz made from
lessons is built from (plan D18).

Why: a quiz can combine up to ten lessons. Every lesson must contribute at least one question, the remainder must go to
the lessons the learner studied most recently, and the model must never be handed lesson text: a prompt that carried ten
whole lessons would cost a fortune and bury the concepts. So each lesson is boiled down, in code and from its stored
plan, to a short summary that fits a token budget, with the least important concepts dropped first.

Use cases:
- questions are split evenly; the remainder goes one each to the most recently created lessons
- the shares always add up to the count asked for
- more lessons than the limit, or fewer questions than lessons, are refused with a reason
- a lesson's summary is built from its plan: title, level, what it covers and its concepts in teaching order, each once
- a summary is never longer than the budget, in tokens estimated as characters divided by four
- when the concepts do not fit, the lowest-priority ones go first (the advanced page's before the introduction's, the
  introduction's before the core's), and what is left stays in teaching order
- lesson text (the pages) never enters a summary
- a plan with nothing in it still gives a summary
"""

from datetime import UTC, datetime, timedelta

import pytest
from support.lesson_data import make_page, make_plan

from graph.quiz_sources import ConceptSummaries, ConceptSummary, SourceSplit, SourceSplitError, TokenEstimate

START = datetime(2026, 1, 1, tzinfo=UTC)


def lessons(count: int) -> list[tuple[str, datetime]]:
    """`count` lessons named a, b, c… made a day apart, oldest first."""
    return [(chr(ord("a") + n), START + timedelta(days=n)) for n in range(count)]


class TestSplitting:
    def test_questions_are_split_evenly(self):
        assert SourceSplit().shares(10, lessons(2)) == {"a": 5, "b": 5}

    def test_the_remainder_goes_one_each_to_the_most_recent_lessons(self):
        assert SourceSplit().shares(10, lessons(3)) == {"a": 3, "b": 3, "c": 4}
        assert SourceSplit().shares(15, lessons(10)) == {
            "a": 1, "b": 1, "c": 1, "d": 1, "e": 1, "f": 2, "g": 2, "h": 2, "i": 2, "j": 2,
        }  # fmt: skip

    def test_the_most_recent_is_by_creation_date_not_by_the_order_given(self):
        shuffled = [("new", START + timedelta(days=9)), ("old", START), ("mid", START + timedelta(days=4))]

        assert SourceSplit().shares(10, shuffled) == {"new": 4, "old": 3, "mid": 3}
        assert list(SourceSplit().shares(10, shuffled)) == ["new", "old", "mid"]  # in the order they were given

    def test_two_lessons_made_at_the_same_moment_are_told_apart_the_same_way_each_time(self):
        same = [("b", START), ("a", START), ("c", START)]

        assert SourceSplit().shares(10, same) == SourceSplit().shares(10, list(reversed(same)))

    def test_one_lesson_takes_every_question(self):
        assert SourceSplit().shares(25, lessons(1)) == {"a": 25}

    @pytest.mark.parametrize("count", [5, 10, 15, 20, 25, 30])
    @pytest.mark.parametrize("n", range(1, 11))
    def test_the_shares_add_up_to_the_count_and_no_lesson_is_left_out(self, n, count):
        if count < n:
            pytest.skip("a count below the number of lessons is refused")
        shares = SourceSplit().shares(count, lessons(n))

        assert sum(shares.values()) == count and min(shares.values()) >= 1
        assert max(shares.values()) - min(shares.values()) <= 1


class TestLimits:
    def test_more_lessons_than_the_limit_are_refused(self):
        with pytest.raises(SourceSplitError, match="at most 10 lessons"):
            SourceSplit().shares(30, lessons(11))

    def test_the_limit_is_a_parameter(self):
        with pytest.raises(SourceSplitError, match="at most 3 lessons"):
            SourceSplit(max_lessons=3).shares(30, lessons(4))

    def test_fewer_questions_than_lessons_are_refused_so_no_lesson_adds_nothing(self):
        with pytest.raises(SourceSplitError, match="at least as many questions as lessons"):
            SourceSplit().shares(5, lessons(6))

    def test_no_lessons_are_refused(self):
        with pytest.raises(SourceSplitError, match="at least one lesson"):
            SourceSplit().shares(10, [])

    def test_the_same_lesson_twice_is_refused(self):
        with pytest.raises(SourceSplitError, match="once"):
            SourceSplit().shares(10, [("a", START), ("a", START)])


class TestTheSummary:
    def test_a_summary_is_the_lessons_title_level_and_what_it_covers(self):
        plan = make_plan()

        summary = ConceptSummaries().of(plan, budget=1500)

        assert summary.title == plan["title"] and summary.level == plan["level"]
        assert plan["summary"] in summary.text()

    def test_the_concepts_come_in_teaching_order_each_once(self):
        plan = make_plan()
        plan["pages"][2]["outline"].append({**plan["pages"][0]["outline"][0]})  # a concept repeated on another page

        summary = ConceptSummaries().of(plan, budget=1500)

        expected = list(dict.fromkeys(i["concept"] for p in plan["pages"] for i in p["outline"]))
        assert [c["concept"] for c in summary.concepts] == expected

    def test_each_concept_carries_the_plans_own_words_and_nothing_from_the_pages(self):
        plan = make_plan()
        pages = {key: make_page(key, plan) for key in ("introduction", "core", "advanced")}

        text = ConceptSummaries().of(plan, budget=1500).text()

        for page in pages.values():
            for section in page["sections"]:
                assert section["body"] not in text
        assert "Explain Halving the range." in text  # the outline's note

    def test_a_summary_never_exceeds_its_budget(self):
        plan = make_plan()
        plan["pages"][1]["outline"] = [
            {"concept": f"Core concept number {n}", "heading": "h", "notes": "n" * 300} for n in range(40)
        ]

        for budget in (200, 400, 800, 1500):
            assert TokenEstimate.of(ConceptSummaries().of(plan, budget=budget).text()) <= budget

    def test_the_lowest_priority_concepts_go_first(self):
        plan = make_plan()
        for page in plan["pages"]:
            page["outline"] = [{"concept": f"{page['key']} {n}", "heading": "h", "notes": "x" * 200} for n in range(3)]
        full = ConceptSummaries().of(plan, budget=5000)
        assert len(full.concepts) == 9 and full.dropped == []
        tight = TokenEstimate.of(full.text()) - 60  # about two concepts too many

        trimmed = ConceptSummaries().of(plan, budget=tight)

        kept = [c["concept"] for c in trimmed.concepts]
        assert trimmed.dropped and set(trimmed.dropped) | set(kept) == {c["concept"] for c in full.concepts}
        assert all(name.startswith("advanced") for name in trimmed.dropped[:2])  # advanced goes first
        assert all(d not in kept for d in trimmed.dropped)
        assert kept == [c["concept"] for c in full.concepts if c["concept"] in kept]  # still in teaching order

    def test_the_core_is_kept_longest_then_the_introduction_and_the_advanced_page_goes_first(self):
        plan = make_plan()
        for page in plan["pages"]:
            page["outline"] = [{"concept": f"{page['key']} {n}", "heading": "h", "notes": "x" * 200} for n in range(3)]
        without_advanced = {
            **plan,
            "pages": [p if p["key"] != "advanced" else {**p, "outline": []} for p in plan["pages"]],
        }
        exactly_the_first_two_pages = TokenEstimate.of(ConceptSummaries().of(without_advanced, budget=5000).text())

        summary = ConceptSummaries().of(plan, budget=exactly_the_first_two_pages)

        assert [c["concept"] for c in summary.concepts] == [
            f"{k} {n}" for k in ("introduction", "core") for n in range(3)
        ]
        assert summary.dropped == ["advanced 2", "advanced 1", "advanced 0"]  # lowest priority first

    def test_a_budget_too_small_for_any_concept_keeps_the_header_and_lists_what_was_left_out(self):
        summary = ConceptSummaries().of(make_plan(), budget=10)

        assert summary.concepts == [] and len(summary.dropped) == 9

    def test_a_plan_with_no_outline_still_gives_a_summary(self):
        plan = make_plan()
        for page in plan["pages"]:
            page["outline"] = []

        summary = ConceptSummaries().of(plan, budget=1500)

        assert summary.concepts == [] and summary.title

    def test_a_summary_survives_being_stored_as_json(self):
        summary = ConceptSummaries().of(make_plan(), budget=1500)

        assert ConceptSummary.from_dict(summary.as_dict()) == summary


class TestTokenEstimate:
    @pytest.mark.parametrize(("text", "tokens"), [("", 0), ("a", 1), ("abcd", 1), ("abcde", 2), ("x" * 4000, 1000)])
    def test_characters_divided_by_four_rounded_up(self, text, tokens):
        assert TokenEstimate.of(text) == tokens
