"""Unit under test: `graph.questions.ExpressionEvaluator`, which computes the answer of a numerical question from the
expression a model wrote (`sqrt(3)/2 * 10`).

Why: the string is written by a model that read text a learner supplied, and it is evaluated by our server. An
evaluator that reaches for `eval` or `sympify` runs whatever that text says. It also decides the answer key, so a wrong
parse marks every learner wrong. It must accept ordinary maths and refuse everything else, in bounded time and memory.

Use cases:
- numbers, + - * / **, unary minus, parentheses and precedence give the right value
- the named functions and constants work, and `log` is base 10 while `ln` is natural
- every rejected construct is refused with a reason: names, calls to anything else, attributes, subscripts, strings,
  lambdas, comprehensions, f-strings, comparisons, booleans, `^` and `%` and `//`, keyword arguments, starred arguments,
  complex numbers, too many or too few arguments
- `__import__`, attribute access and builtins are refused
- an expression over 200 characters or nested deeper than the limit is refused, and so is a huge exponent
  (`9**9**9`), a huge result, a division by zero, a domain error and anything not finite
- a 10 MB string is refused before it is parsed
- the result is always a finite float
"""

import math

import pytest

from graph.questions import ExpressionError, ExpressionEvaluator

ev = ExpressionEvaluator()


@pytest.mark.parametrize(
    ("expression", "value"),
    [
        ("2 + 3", 5),
        ("2 - 3", -1),
        ("2 * 3", 6),
        ("7 / 2", 3.5),
        ("2 ** 10", 1024),
        ("-4", -4),
        ("+4", 4),
        ("--4", 4),
        ("2 + 3 * 4", 14),
        ("(2 + 3) * 4", 20),
        ("2 ** 3 ** 2", 512),
        ("-2 ** 2", -4),
        ("10 / 4 / 5", 0.5),
        ("1e3", 1000),
        (".5 + .25", 0.75),
        ("sqrt(3) / 2 * 10", math.sqrt(3) / 2 * 10),
        ("sqrt(16)", 4),
        ("sin(pi / 2)", 1),
        ("cos(0)", 1),
        ("tan(0)", 0),
        ("asin(1)", math.pi / 2),
        ("acos(1)", 0),
        ("atan(1)", math.pi / 4),
        ("log(1000)", 3),
        ("ln(e)", 1),
        ("exp(0)", 1),
        ("abs(-3.5)", 3.5),
        ("2 * pi * 3", 2 * math.pi * 3),
        ("e ** 2", math.e**2),
        ("sqrt(abs(-16)) + ln(exp(2))", 6),
    ],
)
def test_ordinary_maths_gives_the_right_value(expression, value):
    assert ev.evaluate(expression) == pytest.approx(value)


def test_the_result_is_a_float_even_for_whole_numbers():
    assert isinstance(ev.evaluate("2 + 3"), float)


@pytest.mark.parametrize(
    "expression",
    [
        "x + 1",  # a name that is not a constant
        "pi2",
        "__import__('os').system('id')",
        "open('/etc/passwd')",
        "print(1)",
        "(1).__class__",
        "pi.real",
        "[1, 2][0]",
        "{1: 2}",
        "'a'",
        "'a' * 3",
        "b'a'",
        "lambda: 1",
        "[x for x in range(3)]",
        "f'{1}'",
        "1 < 2",
        "1 if 2 else 3",
        "True",
        "None",
        "2 ^ 3",
        "7 % 3",
        "7 // 2",
        "1 and 2",
        "not 1",
        "~1",
        "1j",
        "sqrt(x=4)",
        "sqrt(*[4])",
        "sqrt()",
        "sqrt(1, 2)",
        "sin",
        "sqrt",
        "(1, 2)",
        "",
        "   ",
        "2 +",
        "sqrt(4",
        "1 2",
        "x := 4",
        "await x",
        "yield",
        "\x00",
    ],
)
def test_everything_else_is_refused(expression):
    with pytest.raises(ExpressionError):
        ev.evaluate(expression)


@pytest.mark.parametrize(
    "expression",
    [
        "9 ** 9 ** 9",
        "10 ** 1001",
        "2 ** -1001",
        "10 ** 400",
        "exp(1000)",
        "1e308 * 10",
        "1 / 0",
        "0 ** -1",
        "sqrt(-1)",
        "log(0)",
        "ln(-1)",
        "asin(2)",
        "acos(2)",
        "(-8) ** 0.5",
        "tan(pi / 2) * 1e300 * 1e300",
    ],
)
def test_out_of_range_and_undefined_results_are_refused(expression):
    with pytest.raises(ExpressionError):
        ev.evaluate(expression)


def test_a_long_expression_is_refused():
    with pytest.raises(ExpressionError, match="200"):
        ev.evaluate("1+" * 100 + "1")


def test_a_huge_string_is_refused_before_it_is_parsed():
    with pytest.raises(ExpressionError, match="200"):
        ev.evaluate("1+" * 5_000_000 + "1")


def test_deep_nesting_is_refused():
    with pytest.raises(ExpressionError):
        ev.evaluate("(" * 60 + "1" + ")" * 60)
    with pytest.raises(ExpressionError):
        ev.evaluate("-" * 60 + "1")
    with pytest.raises(ExpressionError):
        ev.evaluate("abs(" * 40 + "1" + ")" * 40)


def test_nesting_within_the_limit_works():
    assert ev.evaluate("(" * 10 + "1" + ")" * 10) == 1
    assert ev.evaluate("abs(" * 5 + "-1" + ")" * 5) == 1


def test_a_non_string_is_refused():
    for value in (None, 4, ["1"]):
        with pytest.raises(ExpressionError):
            ev.evaluate(value)


def test_an_error_is_a_value_error_with_a_readable_reason():
    with pytest.raises(ValueError, match="not allowed"):
        ev.evaluate("open('x')")
