"""How the app compares two names of the same thing: ignoring case, punctuation and spacing. Pure, and free of any
other `graph` import so the schemas, the validators and the question code can all share it."""

import re


class Normal:
    @staticmethod
    def text(value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", value.lower())).strip()
