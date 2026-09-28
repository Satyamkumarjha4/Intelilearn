"""Chooses the database from the environment.

- SUPABASE_DATABASE_URL set  -> "default" is Supabase, and "local" is the docker Postgres,
                                kept as the source for syncing local data up to Supabase.
- SUPABASE_DATABASE_URL empty -> "default" is the docker Postgres.
- Under pytest               -> always the docker Postgres, never Supabase. A second
                                "local" alias (its own test database) exists so the sync can be tested.
"""

from urllib.parse import quote


def local_database_url(host: str, port: int, name: str, user: str, password: str) -> str:
    return f"postgres://{quote(user)}:{quote(password)}@{host}:{port}/{quote(name)}"


def build_databases(env, *, local_url: str, supabase_url: str, testing: bool) -> dict:
    conn_max_age = env.int("DB_CONN_MAX_AGE", default=60)

    def config(url: str) -> dict:
        db = env.db_url_config(url)
        db["CONN_MAX_AGE"] = conn_max_age
        db["CONN_HEALTH_CHECKS"] = True
        return db

    if testing:
        local = config(local_url)
        local["TEST"] = {"NAME": f"test_{local['NAME']}_local"}
        return {"default": config(local_url), "local": local}

    if supabase_url:
        return {"default": config(supabase_url), "local": config(local_url)}

    return {"default": config(local_url)}
