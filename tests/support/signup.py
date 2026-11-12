"""Signing up in tests: the two-step flow (a code by email, then the code) behind one helper.

`signup.complete(...)` registers and verifies with the code the mailbox holds; the pieces are there for a test that
wants to stop half way. The client keeps its cookies, so the `lc_signup` ticket travels like a browser's."""

from support.mail import MAILBOX

PASSWORD = "correct-horse-battery-staple"


class Signup:
    def __init__(self, client, capture_on_commit):
        self.client, self._capture = client, capture_on_commit

    @staticmethod
    def new(**fields) -> dict:
        return {
            "name": "Grace Hopper",
            "email": "grace.new@example.com",
            "password": PASSWORD,
            "accept_terms": True,
            **fields,
        }

    def register(self, **fields):
        """POST /auth/register; the queued mail is delivered (the transaction commits) before this returns."""
        with self._capture(execute=True):
            return self.client.post("/api/auth/register", self.new(**fields), format="json")

    def code(self, email: str, kind: str = "signup_code") -> str:
        return MAILBOX.code_for(email, kind)

    def verify(self, email: str, code: str | None = None, purpose: str = "signup"):
        code = code if code is not None else self.code(email, "signup_code" if purpose == "signup" else "login_code")
        with self._capture(execute=True):
            return self.client.post(
                "/api/auth/verify", {"email": email, "code": code, "purpose": purpose}, format="json"
            )

    def login(self, email: str, password: str = PASSWORD):
        """POST /auth/login; a code mailed because the account was never verified is delivered before this returns."""
        with self._capture(execute=True):
            return self.client.post("/api/auth/login", {"email": email, "password": password}, format="json")

    def resend(self, email: str, purpose: str = "signup"):
        with self._capture(execute=True):
            return self.client.post("/api/auth/verify/resend", {"email": email, "purpose": purpose}, format="json")

    def complete(self, **fields):
        """Register, then enter the code that was mailed: the response of the verify (the account and its cookies)."""
        registered = self.register(**fields)
        assert registered.status_code == 202, registered.content
        return self.verify(self.new(**fields)["email"])
