"""Unit under test: `graph.questions.BlueprintSampler`, which fills cells from questions that were written but never
served before anything is generated.

Why: with the test fixed at ten cells and every retake generating a fresh set, leftovers are rare, but they are paid
for. The sampler spends them first and reports exactly which cells it could not fill, so only those are generated. A
draw must be reproducible and must never serve a question twice.

Use cases:
- a cell is filled by an unserved question of the same type and difficulty
- retired questions are never drawn, and a question fills at most one cell
- the cells it cannot fill are reported exactly, in order
- the same seed draws the same questions and another seed may draw others
- with nothing to draw from every cell is empty
"""

from graph.questions import BlueprintSampler, LessonTestBlueprint
from graph.questions.blueprint import Cell

CELLS = LessonTestBlueprint.for_topic(False).cells


def pool(kind, difficulty, count, prefix="q", **extra):
    return [{"id": f"{prefix}{n}", "type": kind, "difficulty": difficulty, **extra} for n in range(count)]


def test_a_cell_is_filled_by_an_unserved_question_of_its_type_and_difficulty():
    candidates = pool("mcq", "easy", 2) + pool("msq", "basic", 1, prefix="m")

    draw = BlueprintSampler().draw(CELLS[:4], candidates, seed="s")

    assert sorted(draw.picks) == [0, 1, 3] and draw.picks[3]["id"] == "m0"
    assert [c.index for c in draw.empty] == [2]


def test_a_retired_question_is_never_drawn():
    candidates = pool("mcq", "easy", 2, retired=True)

    draw = BlueprintSampler().draw(CELLS[:2], candidates, seed="s")

    assert draw.picks == {} and [c.index for c in draw.empty] == [0, 1]


def test_a_question_fills_at_most_one_cell():
    draw = BlueprintSampler().draw(CELLS[:2], pool("mcq", "easy", 1), seed="s")

    assert len(draw.picks) == 1 and len(draw.empty) == 1
    assert len({q["id"] for q in draw.picks.values()}) == len(draw.picks)


def test_the_same_seed_draws_the_same_questions():
    candidates = pool("mcq", "easy", 12)
    cell = [Cell(index=0, type="mcq", difficulty="easy", marks=1)]

    picks = {seed: BlueprintSampler().draw(cell, candidates, seed=seed).picks[0]["id"] for seed in ("a", "b", "c", "d")}
    again = {seed: BlueprintSampler().draw(cell, candidates, seed=seed).picks[0]["id"] for seed in ("a", "b", "c", "d")}

    assert picks == again and len(set(picks.values())) > 1


def test_with_nothing_to_draw_from_every_cell_is_empty():
    draw = BlueprintSampler().draw(CELLS, [], seed="s")

    assert draw.picks == {} and [c.index for c in draw.empty] == list(range(10))
