"""Unit under test: `onboarding.router.TopicRouter` and its rules, which pick the catalogue list a learner's answers
lead to.

Why: the list decides what a learner is first offered, and whether a model is needed at all. A school learner must get
their class (not an interview list because they ticked "interview prep"), a computer scientist their own field, and only
a field the catalogue truly does not know may go to a model. The key that comes with each list is what the cache uses,
so it must be the same for the same answers and different for different ones.

Use cases:
- school: the learner's class, or the general school list when there is no class the catalogue covers; goal does not
  matter
- interview preparation (outside school) gets the interview list whatever the education level
- undergraduate and postgraduate with a known field get the field family's list for their level
- undergraduate and postgraduate with no field (or none with letters in it) get the general list for their level
- undergraduate and postgraduate with a field nobody matches get the general list too, marked as not matched, so a model
  may be asked and this list is the fallback
- professionals and self-learners get their own lists
- the key tells the lists apart: class, family or field slug, level
- a new rule is a new class in the router's list: an unknown education level falls to the self-learner list, and a
  router whose rules leave someone out says so instead of guessing
"""

import pytest

from onboarding.catalogue import Catalogue
from onboarding.domain import SuggestionRequest
from onboarding.router import InterviewRule, TopicRouter

catalogue = Catalogue.default()
router = TopicRouter(catalogue)


def route(**fields):
    return router.route(SuggestionRequest(**{"education_level": "school", "goal": "exam_prep", **fields}))


def test_school_gets_the_learners_class():
    result = route(grade_or_year="Class 9")

    assert result.items == catalogue.school(9)
    assert (result.matched, result.key) == (True, "school:class-9")


def test_school_without_a_covered_class_gets_the_general_list():
    for grade in ("", "Class 3", "college"):
        result = route(grade_or_year=grade)

        assert result.items == catalogue.school(None)
        assert result.key == "school:general"


def test_goal_does_not_move_a_school_learner_off_their_class():
    assert route(grade_or_year="9", goal="interview_prep").items == catalogue.school(9)


@pytest.mark.parametrize("level", ["undergraduate", "postgraduate", "professional", "self_learner"])
def test_interview_preparation_gets_the_interview_list(level):
    result = route(education_level=level, goal="interview_prep", field_of_study="Computer Science")

    assert result.items == catalogue.interview_prep()
    assert (result.matched, result.key) == (True, "interview")


@pytest.mark.parametrize("level", ["undergraduate", "postgraduate"])
def test_a_known_field_gets_its_familys_list_for_the_level(level):
    result = route(education_level=level, field_of_study="B.Tech CSE")

    assert result.items == catalogue.family("computer_science", level)
    assert (result.matched, result.key) == (True, f"{level}:computer_science")


@pytest.mark.parametrize("field", ["", "   ", "???"])
def test_no_field_gets_the_general_list_for_the_level(field):
    result = route(education_level="postgraduate", field_of_study=field)

    assert result.items == catalogue.general("postgraduate")
    assert (result.matched, result.key) == (True, "postgraduate:general")


def test_an_unknown_field_gets_the_general_list_marked_as_not_matched():
    result = route(education_level="undergraduate", field_of_study="Architecture")

    assert result.items == catalogue.general("undergraduate")
    assert (result.matched, result.key) == (False, "undergraduate:field-architecture")


def test_professionals_and_self_learners_get_their_own_lists():
    assert route(education_level="professional").items == catalogue.professional()
    assert route(education_level="self_learner").items == catalogue.self_learner()


def test_the_key_tells_different_answers_apart():
    keys = {
        route(grade_or_year="9").key,
        route(grade_or_year="10").key,
        route(education_level="undergraduate", field_of_study="Physics").key,
        route(education_level="postgraduate", field_of_study="Physics").key,
        route(education_level="undergraduate", field_of_study="Architecture").key,
        route(education_level="undergraduate", field_of_study="Pharmacy").key,
        route(education_level="professional").key,
        route(education_level="self_learner").key,
    }

    assert len(keys) == 8


def test_an_unknown_education_level_falls_to_the_self_learner_list():
    assert route(education_level="astronaut").items == catalogue.self_learner()


def test_a_router_whose_rules_leave_someone_out_says_so():
    with pytest.raises(LookupError, match="no routing rule"):
        TopicRouter(catalogue, rules=[InterviewRule()]).route(SuggestionRequest("school", "exam_prep"))
