"""Unit under test: `live.golden.LessonChecks`, what the golden-topic live suite checks in a finished lesson.

Why: the live suite is only worth running if its checks are right: one that passes a lesson with an empty page, or
fails a good one, makes a real-model run (slow and not free) meaningless. These tests run offline in `make check`.

Use cases:
- a complete lesson on the topic passes
- missing or thin pages, too few sections, and placeholder text are each reported by page
- a lesson that hardly mentions its topic is reported, and the keywords needed depend on the topic
- a test with too few questions, too few kinds, repeated ids or no marks is reported
- a missing document or incomplete stored code is reported
- too many degradation warnings are reported, and a topic that wants a picture needs one
"""

import pytest
from live.golden import GOLDEN_TOPICS, GoldenTopic, LessonChecks
from support.lesson_data import make_final_test

TOPIC = GoldenTopic("Binary search", ("sorted", "middle", "half"), min_keywords=2)
checks = LessonChecks()


def body(extra=""):
    return ("Binary search works on a sorted list by checking the middle item and discarding half. " * 8) + extra


def page(sections=3, words_text=None):
    return {
        "key": "x", "title": "T", "summary": "A short recap.",
        "sections": [{"id": f"s{n}", "heading": f"Part {n}", "body": words_text or body()} for n in range(sections)],
    }  # fmt: skip


def lesson(**over):
    base = {
        "pages": {key: page() for key in LessonChecks.PAGES},
        "final_test": make_final_test(),
        "code": "function LessonDocument() {}",
        "code_parts": {"pages": dict.fromkeys(LessonChecks.PAGES, "code"), "interactives": {}},
        "warnings": [],
        "media": 0,
    }
    return base | over


def test_a_complete_lesson_passes():
    assert checks.problems(lesson(), TOPIC) == []


def test_the_golden_topics_are_distinct_and_have_enough_keywords_to_be_demanding():
    topics = [g.topic for g in GOLDEN_TOPICS]

    assert len(set(topics)) == len(topics) >= 3
    assert all(len(g.keywords) >= g.min_keywords >= 2 for g in GOLDEN_TOPICS)


class TestPages:
    def test_a_missing_page_is_reported(self):
        pages = {k: page() for k in ("introduction", "core")}

        assert "The advanced page is missing." in checks.problems(lesson(pages=pages), TOPIC)

    def test_too_few_sections_and_a_thin_page_are_reported_for_that_page(self):
        pages = {"introduction": page(), "core": page(sections=2), "advanced": page(sections=3, words_text="Short.")}

        problems = checks.problems(lesson(pages=pages), TOPIC)

        assert "The core page has 2 sections; at least 3 are expected." in problems
        assert any(p.startswith("The advanced page is thin:") for p in problems)

    @pytest.mark.parametrize(
        "leak", ["Lorem ipsum dolor", "TODO write this", "As an AI language model I", "[insert example]"]
    )
    def test_placeholder_text_is_reported(self, leak):
        pages = {k: page() for k in LessonChecks.PAGES} | {"core": page(words_text=body(leak))}

        assert any("placeholder text" in p for p in checks.problems(lesson(pages=pages), TOPIC))

    def test_a_lesson_that_hardly_mentions_its_topic_is_reported(self):
        generic = "Learning is a process of understanding ideas and applying them carefully to problems. " * 12
        pages = {k: page(words_text=generic) for k in LessonChecks.PAGES}

        problems = checks.problems(lesson(pages=pages), TOPIC)

        assert any(p.startswith("The pages hardly mention Binary search") for p in problems)

    def test_the_keywords_needed_depend_on_the_topic(self):
        biology = GoldenTopic("Photosynthesis", ("chlorophyll", "glucose"), min_keywords=2)

        assert checks.problems(lesson(), biology)[0].startswith("The pages hardly mention Photosynthesis")


class TestTest:
    def test_too_few_questions_and_kinds_are_reported(self):
        few = {"questions": [q for q in make_final_test()["questions"] if q["type"] == "mcq"][:2]}

        problems = checks.problems(lesson(final_test=few), TOPIC)

        assert "The test has 2 questions; at least 8 are expected." in problems
        assert "The test uses fewer than 3 kinds of question." in problems

    def test_repeated_ids_and_a_test_worth_nothing_are_reported(self):
        questions = [dict(q, id="t1", marks=0) for q in make_final_test()["questions"]]

        problems = checks.problems(lesson(final_test={"questions": questions}), TOPIC)

        assert "The test has repeated question ids." in problems and "The test is worth no marks." in problems


class TestDocumentAndWarnings:
    def test_a_missing_document_and_incomplete_code_are_reported(self):
        problems = checks.problems(lesson(code="", code_parts={"pages": {"core": "x"}}), TOPIC)

        assert "The lesson has no document to show." in problems
        assert "The stored code does not hold the three reading pages." in problems

    def test_too_many_degradation_warnings_are_reported(self):
        warnings = [f"warning {n}" for n in range(4)]

        problems = checks.problems(lesson(warnings=warnings), TOPIC)

        assert problems[0].startswith(
            "The lesson came out with 4 degradation warnings: warning 0; warning 1; warning 2"
        )

    def test_a_topic_that_wants_a_picture_needs_one(self):
        wants = GoldenTopic("Amoeba", ("sorted", "middle"), wants_picture=True)

        assert checks.problems(lesson(), wants) == ["A lesson on Amoeba should have a real picture, and has none."]
        assert checks.problems(lesson(media=1), wants) == []
