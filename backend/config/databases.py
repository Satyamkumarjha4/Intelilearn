"""Chooses the database from the environment.

- SUPABASE_DATABASE_URL set  -> "default" is Supabase, and "local" is the docker Postgres,
                                kept as the source for syncing local data up to Supabase.
- SUPABASE_DATABASE_URL empty -> "default" is the docker Postgres.
- Under pytest               -> always the docker Postgres, never Supabase. A second
                                "local" alias (its own test database) exists so the sync can be tested.
"""

from urllib.parse import quote


class DatabaseConfig:
    """Builds Django's DATABASES from the environment (used by settings.py, which stays a module)."""

    def __init__(self, env, conn_max_age: int | None = None):
        self._env = env
        self._conn_max_age = conn_max_age if conn_max_age is not None else env.int("DB_CONN_MAX_AGE", default=60)

    @staticmethod
    def local_url(host: str, port: int, name: str, user: str, password: str) -> str:
        return f"postgres://{quote(user)}:{quote(password)}@{host}:{port}/{quote(name)}"

    def build(self, *, local_url: str, supabase_url: str, testing: bool) -> dict:
        if testing:
            local = self._config(local_url)
            local["TEST"] = {"NAME": f"test_{local['NAME']}_local"}
            return {"default": self._config(local_url), "local": local}
        if supabase_url:
            return {"default": self._config(supabase_url), "local": self._config(local_url)}
        return {"default": self._config(local_url)}

    def _config(self, url: str) -> dict:
        db = self._env.db_url_config(url)
        db["CONN_MAX_AGE"] = self._conn_max_age
        db["CONN_HEALTH_CHECKS"] = True
        return db
