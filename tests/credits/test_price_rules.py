"""Unit under test: the price rules (`credits.pricing.rules`: `PriceRule` and its seven subclasses, the `PriceRules`
registry), `PriceQuoter`, and `JourneyQuote`, against the plan's whole pricing matrix (§5.4) and the totals a learner is
shown (§5.5, as corrected by changelog P2).

Why: this is what a learner is charged. Every row of the matrix is a promise made in the spec, so each is one line of a
table here, computed from the very hints the services send (`size_of` of the real services where there is one). If a
rule
read a hint wrongly, or the price table were edited into a mistake, a row would say so. The same rules answer the gate
and the quote screen, so a learner is never shown one price and charged another.

Use cases:
- `lesson.create`: all fifteen ways in (Quick check, self-rating, quiz result; lesson or one or two sheets; direct or
  recommended), including that a sheets lesson from a Quick check costs 3 for one sheet or two with no discount, and
  that
  a self-rated or quiz-result sheets lesson costs 2 per sheet
- `lesson.continue`: the lesson is 7 at any score; sheets after a Quick check are 2 for both and 0 for one, whatever the
  score; the mastery choice of sheets is 2
- `lesson.followup` 5 and 7; `test.retake` 2 from any attempt; `sheet.generate` 2 per sheet, 1 more once when the sheets
  rest on a lesson's pages
- `quiz.create`: the twelve prices (six counts, with and without the one extra for a quiz from lessons or with the
  warm-up, never both); `quiz.retake`: the same tiers, the extra only for a quiz from lessons
- every journey total of §5.5: due now, later and total, with no range anywhere
- the lines of a quote add up to its total and carry the learner's words
- a hint that is missing, unknown or malformed is refused, naming the hint, and nothing is priced
- every metered action has a rule, and the registry refuses an action that has none
- a price edited in the table is the price quoted
"""

import pytest
from support.pricing_matrix import JOURNEYS, MATRIX, continue_size, create, quiz_size

from credits.pricing.book import PriceBook
from credits.pricing.hints import UnknownHints
from credits.pricing.journey import JourneyQuote
from credits.pricing.quoter import PriceQuoter
from credits.pricing.rules import PriceRule, PriceRules
from credits.pricing.seed import PriceSeed
from credits.refusals import PriceUnavailable
from lessons.metering import MeteredAction

pytestmark = pytest.mark.django_db

CREATE, CONTINUE, FOLLOWUP = MeteredAction.LESSON_CREATE, MeteredAction.LESSON_CONTINUE, MeteredAction.LESSON_FOLLOWUP
RETAKE, QUIZ, QUIZ_RETAKE, SHEET = (
    MeteredAction.TEST_RETAKE,
    MeteredAction.QUIZ_CREATE,
    MeteredAction.QUIZ_RETAKE,
    MeteredAction.SHEET_GENERATE,
)


@pytest.fixture(autouse=True)
def prices(db):
    PriceSeed().apply()
    PriceBook.clear()


def test_the_matrix_has_every_way_the_plan_lists():
    assert len(MATRIX) == 15 + 7 + 2 + 2 + 6 + 6 * 7  # create, continue, followup, retake, sheet, and the quizzes


@pytest.mark.parametrize(("action", "size", "credits", "keys"), MATRIX)
def test_every_row_of_the_matrix_costs_what_the_plan_says(action, size, credits, keys):
    quote = PriceQuoter().quote(action, size)

    assert quote.total == credits
    assert [line.key for line in quote.lines] == keys
    assert sum(line.credits for line in quote.lines) == quote.total


def test_the_price_table_is_the_plans_table():
    assert PriceSeed.PRICES == {
        "lesson.check": 3, "lesson.check_recommended": 2, "lesson.full": 10, "lesson.full_recommended": 9,
        "lesson.full_from_quiz": 9, "lesson.rest": 7, "sheets.after_check": 2, "sheets.after_check_single": 0,
        "sheet.each": 2, "sheet.grounded_extra": 1, "followup.foundation": 5, "followup.advanced": 7,
        "test.retake": 2, "quiz.tier_5": 1, "quiz.tier_10": 2, "quiz.tier_20": 3, "quiz.extra": 1, "streak.repair": 1,
    }  # fmt: skip


@pytest.mark.parametrize(("action", "size", "due_now", "later", "total"), JOURNEYS)
def test_every_journey_total_is_what_the_learner_is_shown(action, size, due_now, later, total):
    journey = JourneyQuote().of(action, size)

    assert (journey.due_now.total, journey.later.total, journey.total) == (due_now, later, total)


def test_a_later_sheet_on_a_sheets_lesson_from_a_quick_check_costs_two():
    quote = PriceQuoter().quote(SHEET, {"sheets": 1, "grounding": "quiz"})

    assert quote.total == 2


def test_the_lines_carry_the_learners_words_from_the_price_table():
    quote = PriceQuoter().quote(CREATE, create("diagnostic", "lesson", "direct"))

    (line,) = quote.lines
    assert (line.key, line.label, line.credits) == ("lesson.check", "Quick check", 3)
    assert quote.as_json() == [{"key": "lesson.check", "label": "Quick check", "credits": 3}]


def test_a_free_price_is_a_price_not_a_missing_one():
    quote = PriceQuoter().quote(CONTINUE, continue_size("sheets_only", sheets=1))

    assert quote.total == 0 and [line.key for line in quote.lines] == ["sheets.after_check_single"]


def test_a_price_edited_in_the_table_is_the_price_quoted():
    from datetime import UTC, datetime

    from credits.pricing.book import PriceCatalog

    PriceCatalog().revise("lesson.rest", 8, by="staff@example.com", now=datetime(2026, 11, 6, tzinfo=UTC))

    assert PriceQuoter().quote(CONTINUE, continue_size("lesson")).total == 8
    assert JourneyQuote().of(CREATE, create("diagnostic", "lesson", "direct")).total == 11


def test_a_missing_price_row_is_unavailable_never_free():
    from credits.models import ActionPrice

    ActionPrice.objects.filter(key="lesson.rest").delete()

    with pytest.raises(PriceUnavailable) as refused:
        PriceQuoter().quote(CONTINUE, continue_size("lesson"))

    assert refused.value.status_code == 503 and refused.value.get_codes() == "price_unavailable"


class TestWhatIsRefused:
    @pytest.mark.parametrize(
        ("action", "size"),
        [
            (CREATE, {}),  # no entry
            (CREATE, {"entry": "teleport", "intent": "lesson", "origin": "direct"}),
            (CREATE, {"entry": "followup", "intent": "lesson", "origin": "followup"}),  # not a way to create
            (CREATE, {"entry": "diagnostic", "intent": "poem", "origin": "direct"}),
            (CREATE, {"entry": "diagnostic", "intent": "lesson", "origin": "mars"}),
            (CREATE, {"entry": "diagnostic", "intent": "sheets", "origin": "direct"}),  # sheets without a count
            (CREATE, {"entry": "diagnostic", "intent": "sheets", "origin": "direct", "sheets": 3}),
            (CREATE, {"entry": "diagnostic", "intent": "sheets", "origin": "direct", "sheets": 0}),
            (CREATE, {"entry": "diagnostic", "intent": "sheets", "origin": "direct", "sheets": "2"}),
            (CREATE, {"entry": "diagnostic", "intent": "sheets", "origin": "direct", "sheets": True}),
            (CREATE, {"entry": "diagnostic", "intent": "lesson", "origin": "direct", "free": True}),  # unknown hint
            (CONTINUE, {}),
            (CONTINUE, {"choice": "everything"}),
            (CONTINUE, {"choice": "sheets_only"}),  # no count
            (CONTINUE, {"choice": "sheets_only", "sheets": 5}),
            (FOLLOWUP, {}),
            (FOLLOWUP, {"followup_level": "expert"}),
            (RETAKE, {"attempt_no": "two"}),
            (RETAKE, {"attempt_no": 2, "discount": 100}),
            (QUIZ, {}),
            (QUIZ, quiz_size(7)),
            (QUIZ, quiz_size(10, "elsewhere")),
            (QUIZ, quiz_size(10, "topic", "guess")),
            (QUIZ, {**quiz_size(10), "num_questions": True}),
            (QUIZ_RETAKE, {"num_questions": 10}),
            (QUIZ_RETAKE, {"num_questions": 10, "source_type": "lessons", "level_mode": "calibration"}),
            (SHEET, {"sheets": 1}),
            (SHEET, {"sheets": 1, "grounding": "the moon"}),
            (SHEET, {"sheets": -1, "grounding": "none"}),
        ],
    )
    def test_a_hint_that_is_missing_unknown_or_malformed_is_refused_and_nothing_is_priced(self, action, size):
        with pytest.raises(UnknownHints):
            PriceQuoter().quote(action, size)

    def test_the_refusal_names_the_hint(self):
        with pytest.raises(UnknownHints) as refused:
            PriceQuoter().quote(CREATE, {"entry": "teleport", "intent": "lesson", "origin": "direct"})

        assert refused.value.field == "entry" and "teleport" in str(refused.value)

    def test_the_sizes_a_gate_could_send_are_not_all_that_is_allowed_only_the_hints_the_rules_read(self):
        read = {name for rule in PriceRules.all() for name in rule.HINTS}

        assert {
            "entry",
            "intent",
            "origin",
            "covers",
            "sheets",
            "grounding",
            "choice",
            "perfect",
            "followup_level",
        } <= read
        assert {"question_count", "attempt_no", "num_questions", "source_type", "sources", "level_mode"} <= read
        assert "has_subjective" in read and "discount" not in read


class TestTheRegistry:
    def test_every_metered_action_has_a_rule(self):
        for action in MeteredAction:
            assert isinstance(PriceRules.for_action(action), PriceRule)

    def test_an_action_with_no_rule_is_refused_not_priced_at_zero(self):
        with pytest.raises(KeyError):
            PriceRules.for_action("lesson.invented")

    def test_each_rule_knows_its_own_action(self):
        assert {rule.action for rule in PriceRules.all()} == set(MeteredAction)

    def test_a_rule_prices_through_the_book_it_is_given(self):
        class Flat:
            def line(self, key):
                from credits.pricing.values import PriceLine

                return PriceLine(key, key, 99)

        rule = PriceRules.for_action(RETAKE, Flat())

        assert rule.quote({"question_count": 10, "attempt_no": 2}).total == 99
