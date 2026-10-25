"""Unit under test: the product name where the backend shows it (`config.urls` admin titles, the OpenAPI document).

Why: the product is called Socra. An operator who opens the admin, or a developer who opens the API docs, should see
that name and not the old one.

Use cases:
- the admin pages carry "Socra admin"
- the OpenAPI document is titled "Socra API"
"""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_the_admin_carries_the_product_name(admin_client):
    page = admin_client.get(reverse("admin:index")).content.decode()

    assert "Socra admin" in page and "Lesson Crafter" not in page


def test_the_api_docs_carry_the_product_name(api_client):
    assert api_client.get("/api/schema?format=json").json()["info"]["title"] == "Socra API"
