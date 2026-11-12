"""Driving the sign-in dance through the real endpoints with the fake provider (the one `accounts.identity.fake` is).

`OAuthFlow.sign_in(...)` does what a browser does: GET the start address (naming who is signing in), follow its
redirect to the callback with the same cookies, and hand back the callback's response. Mail and the grant after the
commit are delivered as in production, through the on-commit capture."""

import json
from urllib.parse import urlsplit

from rest_framework.test import APIClient

DEFAULT = {"subject": "sub-1", "email": "new.person@example.com", "email_verified": True, "name": "New Person"}


class OAuthFlow:
    def __init__(self, client: APIClient, capture_on_commit):
        self.client, self._capture = client, capture_on_commit

    def start(self, identity: dict | None = None, provider: str = "fake", **query):
        who = {**DEFAULT, **(identity or {})}
        with self._capture(execute=True):
            return self.client.get(f"/api/auth/oauth/{provider}/start", {"fake": json.dumps(who), **query})

    def callback(self, redirect, **params):
        """The callback the start redirected to (or one with `params` replaced), with this client's cookies."""
        target = urlsplit(redirect["Location"])
        path = target.path
        query = {key: value for key, value in (pair.split("=", 1) for pair in target.query.split("&") if pair)}
        query.update(params)
        with self._capture(execute=True):
            return self.client.get(path, query)

    def sign_in(self, identity: dict | None = None, **query):
        started = self.start(identity, **query)
        assert started.status_code == 302, started.content
        return self.callback(started)
