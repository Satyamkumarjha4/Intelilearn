"""Signed, expiring media URLs: `/api/media/{asset_id}?exp=…&sig=…`.

Lesson media is shown inside a sandboxed iframe with an opaque origin, which sends no cookies. The URL itself therefore
carries the permission: an HMAC of the asset id and the expiry under the server's secret key.
"""

import hashlib
import hmac
import time
from collections.abc import Callable

from django.conf import settings


class MediaUrlSigner:
    def __init__(self, secret: str | None = None, ttl_s: int | None = None, clock: Callable[[], float] = time.time):
        self.secret = (secret if secret is not None else settings.SECRET_KEY).encode()
        self.ttl_s = ttl_s if ttl_s is not None else settings.MEDIA_URL_TTL_S
        self.clock = clock

    def sign(self, asset_id: str) -> str:
        expires = int(self.clock()) + self.ttl_s
        return f"/api/media/{asset_id}?exp={expires}&sig={self._signature(asset_id, expires)}"

    def verify(self, asset_id: str, exp: str, sig: str) -> bool:
        try:
            expires = int(exp)
        except (TypeError, ValueError):
            return False
        if expires < self.clock():
            return False
        return hmac.compare_digest(self._signature(asset_id, expires), str(sig))

    def _signature(self, asset_id: str, expires: int) -> str:
        return hmac.new(self.secret, f"{asset_id}:{expires}".encode(), hashlib.sha256).hexdigest()
