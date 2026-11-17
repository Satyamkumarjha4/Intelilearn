"""How the app decides that two pieces of text are the same. Pure, and free of any other `graph` import so the schemas,
the validators and the question code can all share it.

There are two questions, and they need two answers. Two *names* of one thing ("Binary-Search!" and "binary search")
differ only by case, punctuation and spacing, so `text` deletes all three. Two *written answers* are another matter:
on a topic about code or maths the punctuation is the answer (`low > high` is not `low == high`, `-1` is not `1`,
`=` is not `!=`), so `written` and `option` keep every symbol and ignore only what a person would: case, spacing, the
`$` and backticks around maths and code, and which dash stands for a minus sign.
"""

import re


class Normal:
    #: the dashes a writer may use for a minus sign
    MINUS = re.compile(r"[\u2010\u2011\u2012\u2013\u2014\u2212]")  # hyphens, dashes and the minus sign
    #: what only marks text up as maths or code: $…$, \(…\), \[…\] and backticks
    MARKUP = re.compile(r"[$`]|\\[()\[\]]")
    #: a LaTeX command (`\frac`, `\times`), which is not a word of the answer
    COMMAND = re.compile(r"\\[a-z]+")
    #: what a value is made of: digits and arithmetic symbols
    VALUE = re.compile(r"[\d\s.,%/+\-*=^(){}<>]+")
    #: what ends an option as a sentence, not as part of the answer (a final "!" or "?" may be: `n!`)
    SENTENCE_END = ".;,"

    @staticmethod
    def text(value: str) -> str:
        """A name: case, punctuation and spacing ignored."""
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", value.lower())).strip()

    @classmethod
    def written(cls, value: str) -> str:
        """Text as written, symbols kept: case, spacing, the minus sign's spelling and maths/code markup ignored."""
        plain = cls.MARKUP.sub("", cls.MINUS.sub("-", value.lower()))
        return re.sub(r"\s+", " ", plain).strip()

    @classmethod
    def numeric(cls, value: str) -> bool:
        """Is the text a value: numbers and arithmetic symbols only, once markup and LaTeX commands are taken away
        (a fraction written in LaTeX, `0.5`, `-12`, `50%`, `2^{10}`)? A word or a variable makes it something else."""
        core = cls.COMMAND.sub("", cls.written(value))
        return bool(cls.VALUE.fullmatch(core)) and any(c.isdigit() for c in core)

    @classmethod
    def option(cls, value: str) -> str:
        """An option of a question: `written`, with every space and a full stop at the end ignored too."""
        return re.sub(r"\s+", "", cls.written(value)).rstrip(cls.SENTENCE_END)
