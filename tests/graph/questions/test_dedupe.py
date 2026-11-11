"""Unit under test: `graph.questions.StemHash` and `QuestionDeduper`, which keep a retake from repeating a question.

Why: a retake that asks the same questions again measures memory, not understanding. The deduper needs no model: an
exact repeat has the same normalised text, a near repeat shares nearly all its words. It is always given the exclusion
list, every stem the lesson has asked, and it decides in order so the earlier question wins.

Use cases:
- the hash of a question ignores case, spacing and sentence punctuation, but not the maths in it
- a question already asked (exact) or nearly asked (almost the same words) is dropped with a reason
- two new questions that repeat each other keep the earlier one
- distinct questions are all kept, in order, and the input is not changed
- a short question is not called a near repeat of a longer one that merely contains its words
- an empty exclusion list drops nothing
- different questions that share only the topic's words, a question frame ("What is the … of a quadratic equation?") or
  the shape of a sum ("Solve $x^2 - 5x + 6 = 0$." and "Solve $x^2 - 7x + 10 = 0$.") are all kept. This guards any
  change to the threshold: lowering `NEAR` to 0.60 flags four of these seven pairs, so it needs more than a number
"""

import pytest

from graph.questions import QuestionDeduper, StemHash


def q(number, text):
    return {"id": f"t{number}", "question": text}


class TestStemHash:
    @pytest.mark.parametrize(
        "other",
        ["what is a prime", "  WHAT   is a prime?? ", "What is a 'prime'?", "What is a prime;"],
    )
    def test_case_spacing_and_sentence_punctuation_do_not_matter(self, other):
        assert StemHash.of(other) == StemHash.of("What is a prime?")

    def test_maths_does_matter(self):
        assert StemHash.of("What is $2+3$?") != StemHash.of("What is $2-3$?")
        assert StemHash.of("Solve x^2 = 4") != StemHash.of("Solve x^3 = 4")

    def test_different_words_give_different_hashes(self):
        assert StemHash.of("What is a prime?") != StemHash.of("What is a composite?")


class TestDeduper:
    ASKED = ["What does binary search do to the range on every step?", "Why must the input be sorted first?"]

    def test_a_question_already_asked_is_dropped(self):
        result = QuestionDeduper().fresh([q(1, "Why must the input be sorted first?")], self.ASKED)

        assert result.kept == [] and [(d[0]["id"], d[1]) for d in result.dropped] == [("t1", "asked before")]

    def test_a_near_repeat_of_a_question_asked_is_dropped(self):
        near = "What does binary search do to the range at every step?"

        result = QuestionDeduper().fresh([q(1, near)], self.ASKED)

        assert result.kept == [] and result.dropped[0][1] == "almost the same as a question asked before"

    def test_two_new_questions_that_repeat_each_other_keep_the_earlier(self):
        first = q(1, "How many comparisons does binary search need for 1024 sorted items?")
        second = q(2, "how many comparisons does binary search need for 1024 sorted items")

        result = QuestionDeduper().fresh([first, second], [])

        assert result.kept == [first] and result.dropped[0][0] is second
        assert result.dropped[0][1] == "repeats another question in this set"

    def test_distinct_questions_are_all_kept_in_order(self):
        asked = [
            q(n, text)
            for n, text in enumerate(
                ["Define a prime number.", "What is the mean of 2, 4, 6?", "Name a sorting method."]
            )
        ]

        result = QuestionDeduper().fresh(asked, self.ASKED)

        assert result.kept == asked and result.dropped == []

    def test_a_short_question_inside_a_long_one_is_not_a_near_repeat(self):
        long_text = "Explain what a prime number is, give three examples, and say why 1 is not one of them."

        result = QuestionDeduper().fresh([q(1, "What is a prime number?")], [long_text])

        assert [k["id"] for k in result.kept] == ["t1"]

    @pytest.mark.parametrize(
        ("asked", "new"),
        [
            ("What is binary search?", "Why does binary search need a sorted list?"),
            ("What does binary search do?", "How many steps does binary search take?"),
            ("Name one use of photosynthesis.", "Where does photosynthesis happen in a plant?"),
            ("What is a quadratic equation?", "What is the discriminant of a quadratic equation?"),
            ("What is the degree of a quadratic equation?", "What is the discriminant of a quadratic equation?"),
            ("Solve $x^2 - 5x + 6 = 0$.", "Solve $x^2 - 7x + 10 = 0$."),
            ("Solve $x^2 - 5x + 6 = 0$.", "Solve $x^2 + 2x - 8 = 0$."),
        ],
    )
    def test_different_questions_that_share_topic_words_a_frame_or_a_sum_shape_are_kept(self, asked, new):
        result = QuestionDeduper().fresh([q(1, new)], [asked])

        assert [k["id"] for k in result.kept] == ["t1"] and result.dropped == []

    def test_nothing_is_dropped_against_an_empty_list(self):
        assert QuestionDeduper().fresh([q(1, "A?")], []).dropped == []

    def test_the_input_is_not_changed(self):
        given = [q(1, "Why must the input be sorted first?")]

        QuestionDeduper().fresh(given, self.ASKED)

        assert given == [q(1, "Why must the input be sorted first?")]
