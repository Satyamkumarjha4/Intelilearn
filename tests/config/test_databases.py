"""Unit under test: `config.databases.DatabaseConfig`, which builds Django's DATABASES from the environment.

Why: it decides which database every request and test writes to. Tests must never reach Supabase, the sync needs the
local database kept as a second alias, and a password with special characters must not corrupt the URL.

Use cases:
- the docker Postgres is "default" when Supabase isn't configured
- with Supabase, it is "default" and the local database is kept as "local" for the sync
- tests always use the docker Postgres, with a separate test database for "local"
- special characters in the password survive
- connections are kept alive (CONN_MAX_AGE) and health-checked
"""

import environ

from config.databases import DatabaseConfig

LOCAL = DatabaseConfig.local_url("db", 5432, "lessoncrafter", "lc", "p@ss:word")
SUPABASE = "postgres://postgres.ref:secret@aws-0-eu.pooler.supabase.com:5432/postgres?sslmode=require"


def build(**kwargs):
    return DatabaseConfig(environ.Env()).build(local_url=LOCAL, **kwargs)


def test_local_postgres_when_supabase_not_configured():
    dbs = build(supabase_url="", testing=False)

    assert set(dbs) == {"default"}
    assert dbs["default"]["HOST"] == "db"


def test_supabase_is_default_and_local_kept_for_sync():
    dbs = build(supabase_url=SUPABASE, testing=False)

    assert dbs["default"]["HOST"] == "aws-0-eu.pooler.supabase.com"
    assert dbs["default"]["OPTIONS"]["sslmode"] == "require"
    assert dbs["local"]["HOST"] == "db"


def test_tests_never_use_supabase():
    dbs = build(supabase_url=SUPABASE, testing=True)

    assert dbs["default"]["HOST"] == "db"
    assert dbs["local"]["TEST"]["NAME"] == "test_lessoncrafter_local"


def test_special_characters_in_password_survive():
    assert build(supabase_url="", testing=False)["default"]["PASSWORD"] == "p@ss:word"


def test_connections_are_kept_alive_and_health_checked():
    db = DatabaseConfig(environ.Env(), conn_max_age=30).build(local_url=LOCAL, supabase_url="", testing=False)[
        "default"
    ]

    assert (db["CONN_MAX_AGE"], db["CONN_HEALTH_CHECKS"]) == (30, True)
