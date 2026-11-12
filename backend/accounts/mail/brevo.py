"""The Brevo adapter (phase 11, D2): a small `httpx` client of Brevo's transactional email API.

The endpoint, the `api-key` header and the body are from Brevo's reference page for "send a transactional email"
(`POST https://api.brevo.com/v3/smtp/email`; `sender`, `to`, `subject`, `htmlContent`, `textContent`; a `201` with a
`messageId`; a `400` with a `code` and a `message`). Which statuses are worth retrying is our rule, not Brevo's
(the page does
not say): a rate limit (429) and server errors (5xx) and a network failure retry, every other refusal does not.
Whether a sender must be verified before sending is not stated on that page either (docs/to_be_developed U1, U2).

The key is never in an error, a log line or a repr.
"""

import html
from email.utils import parseaddr

import httpx
from django.conf import settings

from .mailer import Mailer, MailMessage, PermanentMailError, SendResult, TransientMailError
from .registry import MailBackends


@MailBackends.register
class BrevoMailer(Mailer):
    key = "brevo"
    BASE_URL = "https://api.brevo.com"
    SEND_PATH = "/v3/smtp/email"
    RETRY_STATUSES = frozenset({429})

    def __init__(self, api_key: str, sender: str, client: httpx.Client | None = None, timeout: float | None = None):
        self._api_key = api_key
        self.sender_name, self.sender_email = parseaddr(sender)
        self._client = client or httpx.Client()
        self._timeout = timeout if timeout is not None else float(settings.MAIL_TIMEOUT_S)

    def __repr__(self) -> str:
        return f"BrevoMailer(sender={self.sender_email!r})"

    @classmethod
    def from_settings(cls) -> "BrevoMailer":
        return cls(api_key=settings.BREVO_API_KEY, sender=settings.MAIL_FROM)

    def missing_config(self) -> list[str]:
        return [
            name
            for name, value in (("BREVO_API_KEY", self._api_key), ("MAIL_FROM", self.sender_email))
            if not value.strip()
        ]

    def send(self, message: MailMessage) -> SendResult:
        body = {
            "sender": {"name": self.sender_name, "email": self.sender_email},
            "to": [{"email": message.to}],
            "subject": message.subject,
            "htmlContent": message.html or self._html_of(message.text),
            "textContent": message.text,
        }
        try:
            response = self._client.post(
                self.BASE_URL + self.SEND_PATH,
                json=body,
                headers={"api-key": self._api_key, "accept": "application/json"},
                timeout=self._timeout,
            )
        except httpx.TransportError as error:  # a timeout or a connection that failed
            raise TransientMailError(f"Brevo could not be reached ({type(error).__name__})") from None
        if response.is_success:
            return SendResult(self._json(response).get("messageId", ""))
        if response.status_code in self.RETRY_STATUSES or response.status_code >= 500:
            raise TransientMailError(f"Brevo answered {response.status_code}")
        raise PermanentMailError(f"Brevo refused it: {self._reason(response)}")

    @staticmethod
    def _html_of(text: str) -> str:
        """Brevo wants an HTML part: the text, escaped, with its lines kept."""
        return "<p>" + html.escape(text).replace("\n", "<br>") + "</p>"

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def _reason(self, response: httpx.Response) -> str:
        """Brevo's error `code` when it is a short plain word or phrase; never its `message`, which can quote the
        address."""
        code = self._json(response).get("code")
        if isinstance(code, str) and 0 < len(code) <= 60 and all(c.isalnum() or c in " _.-" for c in code):
            return code
        return f"HTTP {response.status_code}"
