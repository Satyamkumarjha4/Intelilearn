class Pager:
    """Pages of four from a list, wrapping around so "show me others" never runs dry."""

    SIZE = 4

    @classmethod
    def page(cls, items: list, page: int) -> list:
        start = (page * cls.SIZE) % len(items)
        return [items[(start + offset) % len(items)] for offset in range(cls.SIZE)]

    @classmethod
    def has_more(cls, items: list) -> bool:
        return len(items) > cls.SIZE
