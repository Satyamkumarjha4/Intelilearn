"""Unit under test: `graph.normal.Normal`, how the app decides that two pieces of text are the same, and the rules that
use it for a question's options (`graph.validators.base.TextRules.option_problems`).

Why: the first version compared options with the same function that compares names (it deletes every symbol), so on a
topic about code or maths, `low > high` and `low == high` both read "low high", `-1` read `1`, and `=`, `==` and `!=`
read as nothing at all. A quiz with four different options was refused as "options must all be different", three times
over, and the lesson failed (measured with the real models: Binary search failed its Quick check in 3 of 5 runs, and
every option set it refused was a set of different answers). The comparison must ignore only what a person ignores.

Use cases:
- names (`Normal.text`) still ignore case, punctuation and spacing
- written text (`Normal.written`) keeps the symbols that carry meaning: operators, signs, brackets, digits, and a
  superscript (`x²` is not `x2`)
- written text ignores case, spacing, the dollar signs, `\\( … \\)` and `\\[ … \\]` and backticks around maths and
  code, and the different dashes that stand for a minus sign
- a value (`Normal.numeric`) is text made only of numbers and arithmetic symbols once the maths markup and LaTeX
  commands are taken away: fractions, decimals, negatives, percentages, powers; a word, a variable or a comparison with
  words is not
- an option (`Normal.option`) also ignores every space and a full stop at the end
- options that only a symbol separates are different: comparisons, signs, operators, formulas, a negative number from
  its positive (the real sets a model wrote, one table)
- options that differ only by case, spacing, a full stop, backticks, dollar signs or a minus sign's spelling repeat
- a blank option repeats another blank one
- "all of the above" style options are still refused
"""

import pytest

from graph.normal import Normal
from graph.validators import TextRules


class TestNames:
    def test_a_name_ignores_case_punctuation_and_spacing(self):
        assert Normal.text("  Binary-Search!  ") == Normal.text("binary   search")


class TestWritten:
    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("low > high", "low == high"),
            ("-1", "1"),
            ("x + y", "x - y"),
            ("n!", "n"),
            ("O(n)", "O(n^2)"),
            (r"\frac{3}{4}", r"\frac{3}{8}"),
            ("x\u00b2", "x2"),  # a superscript two is a square, not a digit
        ],
    )
    def test_keeps_the_symbols_that_carry_meaning(self, left, right):
        assert Normal.written(left) != Normal.written(right)

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("Low > High", "low > high"),
            ("low   >  high", "low > high"),
            ("$low > high$", "low > high"),
            (r"\(\frac{3}{4}\)", r"\frac{3}{4}"),
            (r"\[x + 1\]", "x + 1"),
            ("`low > high`", "low > high"),
            ("−1", "-1"),  # the minus sign
            ("–1", "-1"),  # an en dash used as one
            ("array.length - 1", "array.length - 1"),  # a narrow no-break space
        ],
    )
    def test_ignores_what_a_person_ignores(self, left, right):
        assert Normal.written(left) == Normal.written(right)


class TestNumeric:
    @pytest.mark.parametrize(
        "value",
        [
            r"\(\frac{3}{4}\)",  # real answers a model wrote for Fractions and decimals
            r"\frac{3}{8}",
            r"$\frac{5}{8}$",
            r"\(\frac{1}{2} + \frac{1}{4}\)",
            "0.3333",
            "-12.5",
            "50%",
            "3/4",
            "2^{10}",
            "7",
        ],
    )
    def test_a_value_is_made_only_of_numbers_and_symbols(self, value):
        assert Normal.numeric(value) is True

    @pytest.mark.parametrize(
        "value", ["low > high", "Photosystem II", "x = 5", "O(log n)", r"\sqrt{x}", "about 3/4", "", " ", "$$"]
    )
    def test_a_word_a_variable_or_nothing_is_not_a_value(self, value):
        assert Normal.numeric(value) is False


class TestOption:
    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("low>high", "low > high"),
            ("Binary search.", "binary   search"),
            ("`x`", "$x$"),
            ("−1", "-1"),
        ],
    )
    def test_ignores_spacing_and_a_final_full_stop(self, left, right):
        assert Normal.option(left) == Normal.option(right)

    def test_keeps_a_final_symbol_that_is_part_of_the_answer(self):
        assert Normal.option("n!") != Normal.option("n")


# Real sets of options a model wrote for Binary search (3 of 5 Quick checks were refused because of them). Each has
# four different answers.
DIFFERENT_OPTIONS = [
    ["low > high", "low == high", "mid == target", "high - low == 1"],
    ["When low > high", "When low == high", "When mid equals target", "When the array length becomes zero"],
    ["0", "1", "The length of the array", "-1"],
    ["0 and $n$", "1 and $n$", "0 and $n-1$", "$-1$ and $n$"],
    ["`=`", "`==`", "`!=`", "`<`"],
    ["a = b", "a == b", "a === b", "a <> b"],
    ["$x < y$", "$x = y$", "$x > y$", "$x != y$"],
    ["low <= high", "low < high", "low == high", "low > high"],
    ["(low + high) / 2", "low + (high - low) / 2", "high - (high - low) / 2", "(low * high) / 2"],
    ["mid = (low + high) / 2", "mid = low + (high - low) / 2", "mid = (low * high) / 2", "mid = high - low"],
    ["0", "1", "array.length - 1", "-1"],
]


class TestOptionProblems:
    @pytest.mark.parametrize("options", DIFFERENT_OPTIONS, ids=lambda o: " | ".join(o)[:50])
    def test_options_that_a_symbol_separates_are_different(self, options):
        assert TextRules.option_problems("Question q1", options) == []

    @pytest.mark.parametrize(
        "options",
        [
            ["Binary search", "binary  search", "linear search", "hashing"],
            ["Binary search.", "Binary search", "linear search", "hashing"],
            ["`low > high`", "$low > high$", "low == high", "mid == target"],
            ["-1", "−1", "0", "1"],
            ["low>high", "low > high", "low == high", "mid == target"],
        ],
    )
    def test_options_that_only_look_different_repeat(self, options):
        assert TextRules.option_problems("Question q1", options) == ["Question q1: options must all be different."]

    def test_two_blank_options_repeat(self):
        assert TextRules.option_problems("Question q1", ["", " ", "a", "b"]) == [
            "Question q1: options must all be different."
        ]

    def test_all_of_the_above_is_still_refused(self):
        problems = TextRules.option_problems("Question q1", ["a", "b", "c", "All of the above"])

        assert problems == ['Question q1: don\'t use "all/none of the above" style options.']
