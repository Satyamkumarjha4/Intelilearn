"""Unit under test: `onboarding.pager.Pager`, which turns a list of topics into pages of four.

Why: "Show me others" has to keep giving fresh topics and never run dry or come back empty. Pages wrap around, so a
learner can keep asking; `has_more` tells the screen whether there is anything else to show.

Use cases:
- page 0 is the first four, page 1 the next four
- a list that does not fill the last page wraps to the start to make four
- paging past the end wraps around, and a huge page number does too
- a list of four or fewer has nothing more to show; a longer one has
- a list shorter than four still gives four (topics repeat) rather than fewer
"""

from onboarding.pager import Pager

ITEMS = list("abcdefg")  # seven


def test_pages_are_four_at_a_time():
    assert Pager.page(ITEMS, 0) == ["a", "b", "c", "d"]
    assert Pager.page(ITEMS, 1) == ["e", "f", "g", "a"]  # the last page wraps to the start to make four


def test_paging_past_the_end_wraps_around():
    assert Pager.page(ITEMS, 2) == ["b", "c", "d", "e"]
    assert Pager.page(ITEMS, 7) == Pager.page(ITEMS, 0)  # 7 pages of four is exactly four laps of seven
    assert len(Pager.page(ITEMS, 10**9)) == 4


def test_has_more_only_when_the_list_is_longer_than_a_page():
    assert Pager.has_more(list("abcd")) is False
    assert Pager.has_more(list("abcde")) is True


def test_a_short_list_still_gives_four():
    assert Pager.page(list("ab"), 0) == ["a", "b", "a", "b"]
