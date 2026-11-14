"""A stand-in for Cloudflare Turnstile in tests: a visitor passes only with the token `GOOD`, and nothing is ever
asked of the network. It remembers what it was asked, so a test can see what reached it."""

from accounts.abuse.captcha import CaptchaVerifier

GOOD = "good-token"


class FakeVerifier(CaptchaVerifier):
    asked: list = []

    def passes(self, token, ip):
        FakeVerifier.asked.append((token, ip))
        return token == GOOD

    @classmethod
    def from_settings(cls) -> "FakeVerifier":
        return cls()
