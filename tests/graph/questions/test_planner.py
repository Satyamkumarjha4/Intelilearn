"""Unit under test: `graph.questions.BatchPlanner`, which splits the cells of a test into the batches a model writes.

Why: "never generate all the questions in one call" only holds if something decides who writes what. The planner gives
each batch an explicit list of cells (type and difficulty), so the union is correct by construction whatever the model
does, and it keeps a quiz from being all long answers by accident (the subjective cap).

Use cases:
- ten cells in batches of five are two batches, and the batch size can be 5 to 10 (a value outside is clamped)
- the cells keep their order and every cell is in exactly one batch
- the batch ids say the round, so a second round for missing cells never reuses an id
- the subjective cap puts at most one long and two short answers in a batch and starts another batch when needed
- the cap is off when the learner picked only short or long answers, or when it is switched off
- the planner reads its size and caps from a settings snapshot, with defaults when a setting is missing
- an empty list of cells gives no batches
"""

import pytest

from graph.questions import BatchPlanner, LessonTestBlueprint
from graph.questions.blueprint import Cell


def cell(index, kind="mcq", difficulty="easy"):
    return Cell(index=index, type=kind, difficulty=difficulty, marks=1)


CELLS = LessonTestBlueprint.for_topic(True).cells


class TestBatchSize:
    def test_ten_cells_in_batches_of_five_are_two_batches_of_five(self):
        batches = BatchPlanner(size=5).plan(CELLS)

        assert [len(b.cells) for b in batches] == [5, 5]
        assert [c.index for b in batches for c in b.cells] == list(range(10))

    @pytest.mark.parametrize(
        ("size", "expected"), [(5, [5, 5]), (6, [6, 4]), (7, [7, 3]), (10, [10]), (4, [5, 5]), (50, [10])]
    )
    def test_the_size_is_five_to_ten(self, size, expected):
        assert [len(b.cells) for b in BatchPlanner(size=size).plan(CELLS)] == expected

    def test_every_cell_is_in_exactly_one_batch(self):
        cells = [cell(n) for n in range(23)]

        planned = [c.index for b in BatchPlanner(size=7).plan(cells) for c in b.cells]

        assert sorted(planned) == list(range(23))

    def test_nothing_to_plan_is_no_batches(self):
        assert BatchPlanner().plan([]) == []


def test_batch_ids_say_which_round_they_belong_to():
    first = BatchPlanner().plan(CELLS, round_no=1)
    second = BatchPlanner().plan(CELLS[:3], round_no=2)

    assert [b.id for b in first] == ["b1-1", "b1-2"] and [b.id for b in second] == ["b2-1"]


class TestSubjectiveCap:
    LONG_AND_SHORT = [cell(n, kind) for n, kind in enumerate(["long_answer"] * 3 + ["short_answer"] * 4 + ["mcq"] * 3)]

    def test_a_batch_holds_at_most_one_long_and_two_short_answers(self):
        batches = BatchPlanner(size=5, max_long=1, max_short=2).plan(self.LONG_AND_SHORT)

        for batch in batches:
            kinds = [c.type for c in batch.cells]
            assert kinds.count("long_answer") <= 1 and kinds.count("short_answer") <= 2
        assert sorted(c.index for b in batches for c in b.cells) == list(range(10))

    def test_the_cap_needs_more_batches_when_there_are_many_subjective_cells(self):
        assert len(BatchPlanner(size=5, max_long=1, max_short=2).plan(self.LONG_AND_SHORT)) == 3

    def test_the_cap_is_off_when_it_is_switched_off(self):
        batches = BatchPlanner(size=5, max_long=1, max_short=2, capped=False).plan(self.LONG_AND_SHORT)

        assert [len(b.cells) for b in batches] == [5, 5]

    @pytest.mark.parametrize(
        ("picked", "applies"),
        [
            (["short_answer"], False),
            (["long_answer"], False),
            (["short_answer", "long_answer"], False),
            (["mcq", "long_answer"], True),
            (["mcq"], True),
            ([], True),
        ],
    )
    def test_the_cap_is_off_only_when_just_short_or_long_answers_were_picked(self, picked, applies):
        assert BatchPlanner.cap_applies(picked) is applies


class TestFromSettings:
    def test_size_and_caps_come_from_the_settings(self):
        planner = BatchPlanner.from_settings({"question_batch_size": 8, "batch_max_long": 2, "batch_max_short": 3})

        assert (planner.size, planner.max_long, planner.max_short) == (8, 2, 3)

    def test_missing_settings_fall_back_to_the_defaults(self):
        planner = BatchPlanner.from_settings({})

        assert (planner.size, planner.max_long, planner.max_short) == (5, 1, 2)
