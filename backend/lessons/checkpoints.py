"""The durable LangGraph checkpointer (Postgres), on the same database as the rest of the app.

A thread can wait at an `interrupt()` for days, so its checkpoints must survive a restart. They live in tables
created by `setup()` (`manage.py setup_checkpointer`, also run by `bootstrap`); they are not Django models.
"""

from contextlib import contextmanager
from urllib.parse import quote, urlencode

from django.db import connection
from langgraph.checkpoint.postgres import PostgresSaver


class CheckpointerFactory:
    def __init__(self, database: dict | None = None):
        # Default to the connection Django is using right now, so tests use their test database.
        self.database = database if database is not None else connection.settings_dict

    def conninfo(self) -> str:
        db = self.database
        info = f"postgresql://{quote(db['USER'], safe='')}:{quote(db['PASSWORD'], safe='')}@{db['HOST']}:"
        info += f"{db['PORT'] or 5432}/{quote(db['NAME'], safe='')}"
        if options := {k: v for k, v in (db.get("OPTIONS") or {}).items() if isinstance(v, str)}:
            info += "?" + urlencode(options)
        return info

    @contextmanager
    def saver(self):
        """A `PostgresSaver` on its own connection, closed when the block ends."""
        with PostgresSaver.from_conn_string(self.conninfo()) as saver:
            yield saver

    def setup(self) -> None:
        """Create the checkpoint tables (idempotent)."""
        with self.saver() as saver:
            saver.setup()
