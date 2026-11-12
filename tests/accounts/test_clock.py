"""Unit under test: `accounts.clock` (`Clock`, `SystemClock`), the one source of "now" the sign-in code reads.

Why: codes expire in minutes, locks in an hour and purges in days. A test that has to wait for that is slow and
flaky, so time
is an injected port (as in `credits`, which `accounts` cannot import: the dependency runs the other way). The test
fake of
`credits` already fits the port.

Use cases:
- the system clock gives an aware UTC time that moves forward
- the fake clock of the tests satisfies the port, so the same fake serves both apps
"""

from datetime import UTC, timedelta

from django.utils import timezone
from support.clock import FakeClock

from accounts.clock import Clock, SystemClock


def test_the_system_clock_gives_an_aware_utc_time_that_moves_forward():
    first = SystemClock().now()
    second = SystemClock().now()

    assert first.tzinfo is UTC and second >= first
    assert abs(first - timezone.now()) < timedelta(seconds=5)


def test_the_fake_clock_of_the_tests_satisfies_the_port():
    clock: Clock = FakeClock()

    assert clock.now() == clock.now()
