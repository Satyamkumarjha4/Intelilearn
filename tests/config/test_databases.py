import environ

from config.databases import build_databases, local_database_url

LOCAL = local_database_url("db", 5432, "lessoncrafter", "lc", "p@ss:word")
SUPABASE = "postgres://postgres.ref:secret@aws-0-eu.pooler.supabase.com:5432/postgres?sslmode=require"


def build(**kwargs):
    return build_databases(environ.Env(), local_url=LOCAL, **kwargs)


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
