"""Unit under test: `graph.quiz_config` (`QuizPresets`, `QuizConfig`, `QuizConfigError`): what a quick quiz is asked to
be, checked in one place for the API and the wizard's rules alike (plan D17, §7.4, §8.5).

Why: a quiz's settings are fixed when it is made (changing them makes a new quiz), they decide what the model is asked
to write, and attempts at "the same quiz" are compared by them. So the rules about the count, the kinds of question and
the level mode must be one class that the server enforces and the frontend mirrors, and the settings must give the same
hash whenever they mean the same thing, however the request was written.

Use cases:
- the question counts are the presets 5, 10, 15, 20, 25 and 30; the default is 10
- a count that is not a preset, a kind of question that does not exist, or no kind at all, is refused with the field
- short and long answers are refused below 10 questions; numerical questions are refused for a topic that is not
  quantitative (when the topic has been judged)
- the level is a self-rating (0.5 to 5 stars), a calibration, or the existing test scores; a rating needs its mode and
  the mode its rating; existing scores need lessons, not a topic
- the kinds are kept once each, in the standard order
- the same settings give the same hash however the topic is spelled or the lessons and kinds are ordered; any real
  difference gives another hash
- a config survives being stored as JSON
- `has_subjective` says whether short or long answers were picked
"""

import pytest

from graph.questions.traits import TopicTraits
from graph.quiz_config import QuizConfig, QuizConfigError, QuizPresets

MATHS = TopicTraits(quantitative=True, programming=False)
HISTORY = TopicTraits(quantitative=False, programming=False)


def make(**overrides) -> QuizConfig:
    fields = {
        "num_questions": 10, "types": ["mcq"], "level": {"mode": "self_rating", "rating": 3}, "traits": MATHS,
        "source_type": "topic",
    }  # fmt: skip
    return QuizConfig.validate(**{**fields, **overrides})


def refused(**overrides) -> QuizConfigError:
    with pytest.raises(QuizConfigError) as raised:
        make(**overrides)
    return raised.value


class TestPresets:
    def test_the_counts_are_the_six_presets(self):
        assert QuizPresets.COUNTS == (5, 10, 15, 20, 25, 30) and QuizPresets.DEFAULT == 10


class TestTheCount:
    @pytest.mark.parametrize("count", [5, 10, 15, 20, 25, 30])
    def test_every_preset_is_accepted(self, count):
        assert make(num_questions=count).num_questions == count

    @pytest.mark.parametrize("count", [0, 1, 7, 12, 31, 50, -5, 2.5, "10", None, True])
    def test_anything_else_is_refused_on_its_field(self, count):
        error = refused(num_questions=count)

        assert error.field == "num_questions" and "5, 10, 15, 20, 25 or 30" in error.message


class TestTheKinds:
    def test_an_unknown_kind_is_refused(self):
        error = refused(types=["mcq", "essay"])

        assert error.field == "types" and "essay" in error.message

    def test_a_code_question_is_not_a_kind_of_its_own(self):
        assert refused(types=["code"]).field == "types"

    def test_no_kind_at_all_is_refused(self):
        assert refused(types=[]).field == "types"

    @pytest.mark.parametrize("kind", ["short_answer", "long_answer"])
    def test_short_and_long_answers_are_refused_in_a_five_question_quiz(self, kind):
        error = refused(num_questions=5, types=["mcq", kind])

        assert error.field == "types" and "10" in error.message

    @pytest.mark.parametrize("kind", ["short_answer", "long_answer"])
    def test_and_accepted_from_ten(self, kind):
        assert make(num_questions=10, types=[kind]).types == (kind,)

    def test_numerical_questions_are_refused_for_a_topic_that_is_not_quantitative(self):
        error = refused(types=["numerical"], traits=HISTORY)

        assert error.field == "types" and "numerical" in error.message

    def test_a_topic_nobody_judged_may_have_any_kind_the_count_allows(self):
        assert make(types=["numerical", "msq"], traits=None).types == ("msq", "numerical")

    def test_the_kinds_are_kept_once_each_in_the_standard_order(self):
        config = make(num_questions=15, types=["long_answer", "mcq", "numerical", "mcq", "msq"])

        assert config.types == ("mcq", "msq", "numerical", "long_answer")

    def test_has_subjective_says_whether_short_or_long_answers_were_picked(self):
        assert make(types=["mcq"]).has_subjective is False
        assert make(types=["mcq", "short_answer"]).has_subjective is True

    def test_only_subjective_kinds_switch_the_per_batch_cap_off(self):
        assert make(types=["short_answer", "long_answer"]).capped is False
        assert make(types=["short_answer", "mcq"]).capped is True


class TestTheLevel:
    def test_a_self_rating_is_stored_in_halves(self):
        config = make(level={"mode": "self_rating", "rating": 3.5})

        assert (config.level_mode, config.self_rating_halves) == ("self_rating", 7)

    @pytest.mark.parametrize("rating", [0, 0.25, 5.5, -1, "3", None, True])
    def test_a_rating_must_be_stars_from_half_a_star_to_five_in_half_steps(self, rating):
        assert refused(level={"mode": "self_rating", "rating": rating}).field == "level"

    def test_a_calibration_has_no_rating(self):
        config = make(level={"mode": "calibration"})

        assert (config.level_mode, config.self_rating_halves) == ("calibration", None)

    def test_a_rating_with_another_mode_is_refused(self):
        assert refused(level={"mode": "calibration", "rating": 3}).field == "level"

    def test_existing_scores_need_lessons(self):
        assert refused(level={"mode": "existing_score"}, source_type="topic").field == "level"
        assert make(level={"mode": "existing_score"}, source_type="lessons").level_mode == "existing_score"

    @pytest.mark.parametrize("level", [{"mode": "telepathy"}, {}, None, "calibration", {"mode": None}])
    def test_an_unknown_mode_is_refused(self, level):
        assert refused(level=level).field == "level"


class TestTheHash:
    def hash(self, config=None, source_type="topic", keys=("Binary search",)):
        return (config or make()).hash(source_type, keys)

    def test_the_same_settings_give_the_same_hash(self):
        assert self.hash() == self.hash()

    def test_it_is_a_sha256_hex_digest(self):
        assert len(self.hash()) == 64 and int(self.hash(), 16) >= 0

    def test_a_topic_is_the_same_whatever_its_case_or_spacing(self):
        assert self.hash(keys=("Binary search",)) == self.hash(keys=("  binary   SEARCH ",))

    def test_lessons_are_the_same_in_any_order(self):
        config = make(level={"mode": "existing_score"}, source_type="lessons")

        assert self.hash(config, "lessons", ("b", "a", "c")) == self.hash(config, "lessons", ("c", "b", "a"))

    def test_kinds_in_any_order_are_the_same_quiz(self):
        one, other = make(num_questions=15, types=["msq", "mcq"]), make(num_questions=15, types=["mcq", "msq"])

        assert self.hash(one) == self.hash(other)

    @pytest.mark.parametrize(
        "other",
        [
            {"num_questions": 15},
            {"types": ["mcq", "msq"]},
            {"level": {"mode": "calibration"}},
            {"level": {"mode": "self_rating", "rating": 4}},
        ],
    )
    def test_a_real_difference_gives_another_hash(self, other):
        assert self.hash(make(**other)) != self.hash()

    def test_another_topic_or_other_lessons_give_another_hash(self):
        assert self.hash(keys=("Sorting",)) != self.hash()
        assert self.hash(source_type="lessons", keys=("a",)) != self.hash(source_type="lessons", keys=("b",))
        assert self.hash(source_type="lessons", keys=("Binary search",)) != self.hash()


class TestStoring:
    def test_a_config_survives_json(self):
        config = make(num_questions=20, types=["mcq", "short_answer"], level={"mode": "calibration"})

        assert QuizConfig.from_dict(config.as_dict()) == config

    def test_the_stored_form_is_plain_json(self):
        assert make().as_dict() == {
            "num_questions": 10, "types": ["mcq"], "level_mode": "self_rating", "self_rating_halves": 6,
        }  # fmt: skip

    def test_a_stored_config_that_is_not_one_is_refused(self):
        with pytest.raises(ValueError):
            QuizConfig.from_dict({"num_questions": 12, "types": ["mcq"], "level_mode": "calibration"})
