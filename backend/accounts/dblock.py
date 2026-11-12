"""A lock that two requests for the same email take turns on (Postgres advisory lock, held until the transaction ends).

A unique index decides who wins a race, but only by failing the loser. For "replace this email's pending sign-up" and
"issue this email's code" the second request should simply wait and then do its own work on what the first left, so
there is always exactly one live row and no request answers with a database error."""

from django.db import connection


class DbLock:
    @staticmethod
    def acquire(name: str) -> None:
        """Waits for the lock named `name`. Must be called inside `transaction.atomic()`; released at its end."""
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [name])
