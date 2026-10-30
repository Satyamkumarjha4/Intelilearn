"""Unit under test: `graph.questions.MarksPolicy`, the table that says what a question is worth.

Why: the marks decide every score, band and follow-up offer. They must come from this table alone, never from a model,
or a model that rates its own easy question as worth 20 marks could decide a learner's result. Legacy questions keep the
marks they were stored with, so the table is only for new ones.

Use cases:
- every cell of the table: five kinds by five difficulties, normal tier for easy, basic and standard, difficult tier
  for difficult and expert
- an old difficulty name (medium, hard) is read as its new one
- a kind with no row (the legacy code kind) and an unknown kind or difficulty are refused
- the tier of a difficulty picks the column
"""

import pytest

from graph.levels import Difficulty
from graph.questions import MarksPolicy

TABLE = {
    "mcq": (1, 2),
    "msq": (2, 3),
    "numerical": (2, 3),
    "short_answer": (2, 3),
    "long_answer": (5, 6),
}
NORMAL = ["easy", "basic", "standard"]
DIFFICULT = ["difficult", "expert"]


@pytest.mark.parametrize(("kind", "normal", "difficult"), [(k, *v) for k, v in TABLE.items()])
def test_every_cell_of_the_table(kind, normal, difficult):
    assert [MarksPolicy.marks(kind, d) for d in NORMAL] == [normal] * 3
    assert [MarksPolicy.marks(kind, d) for d in DIFFICULT] == [difficult] * 2


def test_an_enum_difficulty_works_too():
    assert MarksPolicy.marks("msq", Difficulty.EXPERT) == 3


@pytest.mark.parametrize(("old", "marks"), [("medium", 1), ("hard", 2), ("MEDIUM", 1)])
def test_an_old_difficulty_name_is_read_as_its_new_one(old, marks):
    assert MarksPolicy.marks("mcq", old) == marks


@pytest.mark.parametrize(("kind", "difficulty"), [("code", "easy"), ("essay", "easy"), ("mcq", "impossible")])
def test_a_kind_without_a_row_or_an_unknown_one_is_refused(kind, difficulty):
    with pytest.raises(ValueError):
        MarksPolicy.marks(kind, difficulty)
