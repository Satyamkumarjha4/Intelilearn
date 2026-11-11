"""Unit under test: the `PASSWORD_HASHERS` setting in `config/settings.py`, which swaps Django's deliberately slow
password hasher for a fast one while the tests run.

Why: PBKDF2 at Django's default strength costs about 0.15 s per hash and per check, and most tests make or check one,
which was two thirds of the suite's run time. The fast hasher is worthless as a password store, so it must exist only
under pytest: if it ever reached a real deployment, every stored password would be an unsalted-strength MD5.

Use cases:
- under the tests, passwords are made and checked with the fast hasher (the speed-up is really on)
- outside the tests (no pytest in the process, so `TESTING` is false), the setting is not overridden and a new
  password is hashed with Django's own default, PBKDF2
- outside the tests, the fast hasher is not in the list of hashers at all, so not even an old stored hash can be read
  with it
"""

import json
import subprocess
import sys

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password

FAST = "django.contrib.auth.hashers.MD5PasswordHasher"
# Runs in a fresh interpreter, where `pytest` is not in sys.modules: it reads the settings as production does.
PROBE = """
import json
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
from django.conf import settings
from django.contrib.auth.hashers import make_password

django.setup()
print(json.dumps({
    "pytest_loaded": "pytest" in sys.modules,
    "testing": settings.TESTING,
    "hashers": list(settings.PASSWORD_HASHERS),
    "algorithm": make_password("a-password").split("$")[0],
}))
"""


def read_settings_outside_the_tests() -> dict:
    done = subprocess.run(
        [sys.executable, "-c", PROBE], cwd=settings.BASE_DIR, capture_output=True, text=True, timeout=120, check=True
    )
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_under_the_tests_passwords_use_the_fast_hasher():
    stored = make_password("a-password")

    assert stored.startswith("md5$")
    assert check_password("a-password", stored)
    assert not check_password("another-password", stored)
    assert settings.PASSWORD_HASHERS == [FAST]


def test_outside_the_tests_the_hasher_is_djangos_own_default():
    seen = read_settings_outside_the_tests()

    assert seen["pytest_loaded"] is False
    assert seen["testing"] is False
    assert seen["algorithm"] == "pbkdf2_sha256"


def test_outside_the_tests_the_fast_hasher_is_not_a_hasher_at_all():
    seen = read_settings_outside_the_tests()

    assert FAST not in seen["hashers"]
    assert seen["hashers"][0] == "django.contrib.auth.hashers.PBKDF2PasswordHasher"
