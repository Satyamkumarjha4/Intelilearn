"""Unit under test: `onboarding.catalogue` (`Catalogue`, `FieldFamilies`) and the shipped `catalogue.json`, the curated
topics every first-topic suggestion starts from.

Why: the catalogue is the instant, free, always-available source, and the fallback when a model fails. If a class has
too few topics the four suggestions repeat; if a field of study lands in the wrong family a computer scientist is
offered poetry; and a malformed file must fail at load, not in a learner's onboarding.

Use cases:
- every class from 6 to 12 has 6 to 10 topics across several subjects, Maths among them
- there is a general school list, a general list for each of undergraduate and postgraduate, a list for each of the
  five field families at both levels, and lists for professionals, interview preparation and self-learners
- every list has at least six topics, and every topic has a subject and an English title
- the field of study is matched to a family by keywords, more specific families first (Computer Science before Science,
  Political Science before Science), whole words only, in any case or punctuation
- a field the catalogue does not know (medicine, architecture) matches nothing, and so does an empty one
- a malformed catalogue (a missing class, a list with fewer than four topics, a topic without a title) is refused
  with a message that names the problem
"""

import copy
import json

import pytest

from onboarding.catalogue import CATALOGUE_PATH, Catalogue, CatalogueError, CatalogueItem

FAMILIES = ["computer_science", "engineering", "commerce_economics", "arts_humanities", "science"]


@pytest.fixture(scope="module")
def raw():
    return json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def catalogue():
    return Catalogue.default()


@pytest.mark.parametrize("grade", range(6, 13))
def test_every_class_has_six_to_ten_topics_across_several_subjects(catalogue, grade):
    topics = catalogue.school(grade)

    assert 6 <= len(topics) <= 10
    assert len({t.subject for t in topics}) >= 3
    assert "Maths" in {t.subject for t in topics}
    assert len({t.title for t in topics}) == len(topics)


def test_every_list_exists_and_is_long_enough(catalogue):
    lists = [catalogue.school(None), catalogue.professional(), catalogue.interview_prep(), catalogue.self_learner()]
    for level in ("undergraduate", "postgraduate"):
        lists.append(catalogue.general(level))
        lists += [catalogue.family(slug, level) for slug in FAMILIES]

    assert all(len(topics) >= 6 for topics in lists)
    assert all(
        isinstance(t, CatalogueItem) and t.subject.strip() and t.title.strip() for topics in lists for t in topics
    )


def test_an_unknown_class_gets_the_general_school_list(catalogue):
    assert catalogue.school(5) == catalogue.school(None)
    assert catalogue.school(13) == catalogue.school(None)


@pytest.mark.parametrize(
    ("field", "family"),
    [
        ("Computer Science", "computer_science"),
        ("B.Tech CSE", "computer_science"),
        ("BCA", "computer_science"),
        ("Data science", "computer_science"),
        ("Mechanical Engineering", "engineering"),
        ("B.Tech", "engineering"),
        ("Electronics and communication", "engineering"),
        ("B.Com", "commerce_economics"),
        ("Economics (Hons)", "commerce_economics"),
        ("MBA finance", "commerce_economics"),
        ("Political Science", "arts_humanities"),
        ("English literature", "arts_humanities"),
        ("Psychology", "arts_humanities"),
        ("B.A. History", "arts_humanities"),
        ("Physics", "science"),
        ("B.Sc Chemistry", "science"),
        ("Environmental science", "science"),
        ("  mathematics ", "science"),
    ],
)
def test_a_field_is_matched_to_its_family(catalogue, field, family):
    assert catalogue.families.match(field) == family


@pytest.mark.parametrize(
    "field", ["Medicine", "Architecture", "Pharmacy", "Culinary arts and hospitality", "", "   ", "???"]
)
def test_a_field_the_catalogue_does_not_know_matches_nothing(catalogue, field):
    # "arts" alone is not a keyword: "Culinary arts" is not humanities.
    assert catalogue.families.match(field) is None


def test_keywords_are_whole_words(catalogue):
    assert catalogue.families.match("Itinerant bakers") is None  # "it" inside a word
    assert catalogue.families.match("Mathematica") is None
    assert catalogue.families.match("it") == "computer_science"


def test_the_family_lists_are_those_of_the_family(catalogue):
    assert "Binary search" in {t.title for t in catalogue.family("computer_science", "undergraduate")}
    assert "Supply and demand" in {t.title for t in catalogue.family("commerce_economics", "undergraduate")}
    assert catalogue.family("science", "undergraduate") != catalogue.family("science", "postgraduate")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["school"]["classes"].pop("9"), "class 9"),
        (lambda d: d["school"]["classes"].__setitem__("9", d["school"]["classes"]["9"][:3]), "class 9"),
        (lambda d: d["professional"].__setitem__(0, {"subject": "Work", "title": ""}), "professional"),
        (lambda d: d["interview_prep"].__setitem__(0, {"subject": "Work"}), "interview_prep"),
        (lambda d: d["higher_education"]["families"][0].pop("keywords"), "computer_science"),
        (lambda d: d["higher_education"]["general"].pop("postgraduate"), "postgraduate"),
    ],
)
def test_a_malformed_catalogue_is_refused_and_says_why(raw, change, message):
    data = copy.deepcopy(raw)
    change(data)

    with pytest.raises(CatalogueError, match=message):
        Catalogue(data)
