from rest_framework.pagination import CursorPagination


class ConsoleCursorPagination(CursorPagination):
    """The cursor pagination of the lessons API (`?cursor=&page_size=`), with the ordering chosen per view: set
    `ordering` on a subclass. Pick a field that does not change, or a page can repeat or skip a row."""

    ordering = "-created_at"
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
