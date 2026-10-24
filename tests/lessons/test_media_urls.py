"""Unit under test: `lessons.media_urls.MediaUrlSigner` and the `GET /api/media/{id}` view that serves lesson media.

Why: lesson media is shown inside a sandboxed iframe with an opaque origin, which sends no cookies, so the image URL
itself must carry the permission. If a signature could be forged, extended or reused for another file, anyone could read
another learner's media; if the view revealed why a request failed it would help guess ids.

Use cases:
- a signed URL verifies for its own asset until it expires
- changing the asset id, the expiry or the signature, an expired URL and a signature from another secret all fail
- malformed signatures and expiries fail instead of raising
- the URL is /api/media/{id}?exp=…&sig=… with the expiry taken from MEDIA_URL_TTL_S
- the view serves the file with its stored content type, nosniff and a private cache header, without any cookie
- an invalid or expired signature, an unknown or malformed id and a file that is gone are all the same 404
- the media folder is not also served unsigned (not even in DEBUG)
"""

import pytest
from django.core.files.base import ContentFile
from support.media import png

from lessons.media_urls import MediaUrlSigner
from lessons.models import MediaAsset

pytestmark = pytest.mark.django_db

ASSET = "5a1b6f0e-5d6e-4ac1-9a6f-0a1b2c3d4e5f"


class Clock:
    def __init__(self, now=1_000_000):
        self.now = now

    def __call__(self):
        return self.now


def query(url: str) -> dict:
    return dict(part.split("=") for part in url.split("?")[1].split("&"))


class TestSigner:
    def test_a_signed_url_verifies_for_its_own_asset(self):
        signer = MediaUrlSigner(secret="s", ttl_s=3600, clock=Clock())

        params = query(signer.sign(ASSET))

        assert signer.verify(ASSET, params["exp"], params["sig"]) is True

    def test_the_url_has_the_documented_shape_and_expiry(self):
        signer = MediaUrlSigner(secret="s", ttl_s=3600, clock=Clock(1000))

        url = signer.sign(ASSET)

        assert url.startswith(f"/api/media/{ASSET}?exp=4600&sig=") and len(query(url)["sig"]) == 64

    def test_the_expiry_comes_from_the_setting_by_default(self, settings):
        settings.MEDIA_URL_TTL_S = 60

        url = MediaUrlSigner(clock=Clock(1000)).sign(ASSET)

        assert query(url)["exp"] == "1060"

    @pytest.mark.parametrize(
        "tamper",
        [
            lambda a, e, s: ("00000000-0000-0000-0000-000000000000", e, s),
            lambda a, e, s: (a, str(int(e) + 1), s),
            lambda a, e, s: (a, e, s[:-1] + ("0" if s[-1] != "0" else "1")),
            lambda a, e, s: (a, e, ""),
            lambda a, e, s: (a, "", s),
            lambda a, e, s: (a, "soon", s),
            lambda a, e, s: (a, e, "zz" * 32),
        ],
        ids=["other-asset", "later-expiry", "changed-signature", "no-signature", "no-expiry", "bad-expiry", "not-hex"],
    )
    def test_anything_changed_fails(self, tamper):
        signer = MediaUrlSigner(secret="s", ttl_s=3600, clock=Clock())
        params = query(signer.sign(ASSET))

        assert signer.verify(*tamper(ASSET, params["exp"], params["sig"])) is False

    def test_an_expired_url_fails(self):
        clock = Clock()
        signer = MediaUrlSigner(secret="s", ttl_s=100, clock=clock)
        params = query(signer.sign(ASSET))

        clock.now += 101

        assert signer.verify(ASSET, params["exp"], params["sig"]) is False

    def test_a_signature_from_another_secret_fails(self):
        params = query(MediaUrlSigner(secret="one", ttl_s=3600, clock=Clock()).sign(ASSET))

        assert (
            MediaUrlSigner(secret="two", ttl_s=3600, clock=Clock()).verify(ASSET, params["exp"], params["sig"]) is False
        )


@pytest.fixture
def asset(lesson, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    asset = MediaAsset(
        id=ASSET, lesson=lesson, spec_id="widget_core", kind="image", mime_type="image/png", source="wikimedia"
    )
    asset.file.save("a.png", ContentFile(png()), save=False)
    asset.save()
    return asset


class TestView:
    def url(self, asset_id=ASSET, **override):
        signed = MediaUrlSigner().sign(asset_id)
        params = query(signed) | override
        return f"/api/media/{asset_id}?exp={params['exp']}&sig={params['sig']}"

    def test_serves_the_file_with_its_type_and_safe_headers_without_any_cookie(self, api_client, asset):
        response = api_client.get(self.url())

        assert response.status_code == 200
        assert b"".join(response.streaming_content) == png()
        assert response["Content-Type"] == "image/png"
        assert response["X-Content-Type-Options"] == "nosniff"
        assert response["Cache-Control"].startswith("private")

    @pytest.mark.parametrize(
        "override",
        [{"sig": "0" * 64}, {"exp": "1"}, {"sig": ""}, {"exp": "x"}],
        ids=["bad-sig", "expired", "no-sig", "bad-exp"],
    )
    def test_an_invalid_or_expired_signature_is_a_404(self, api_client, asset, override):
        response = api_client.get(self.url(**override))

        assert response.status_code == 404 and response.json()["code"] == "not_found"

    def test_missing_parameters_are_a_404(self, api_client, asset):
        assert api_client.get(f"/api/media/{ASSET}").status_code == 404

    def test_an_unknown_asset_is_the_same_404(self, api_client, asset):
        other = "00000000-0000-0000-0000-000000000001"

        assert api_client.get(self.url(other)).status_code == 404

    def test_a_malformed_id_is_a_404(self, api_client, asset):
        assert api_client.get("/api/media/not-a-uuid?exp=1&sig=x").status_code == 404

    def test_a_file_that_is_gone_is_a_404(self, api_client, asset, tmp_path):
        for path in tmp_path.rglob("*.png"):
            path.unlink()

        assert api_client.get(self.url()).status_code == 404

    def test_the_schema_documents_the_endpoint(self, api_client):
        assert "/api/media/{asset_id}" in api_client.get("/api/schema?format=json").json()["paths"]


def test_the_media_folder_is_not_served_unsigned(api_client, asset, settings):
    settings.DEBUG = True

    assert api_client.get(f"/media/{asset.file.name}").status_code == 404
