"""Unit under test: `marketing.admin.DemoQuestionAdmin`, how the question bank is looked after in the Django admin.

Why: the bank is edited by hand and there are only 25 questions to start with. Whoever curates it needs to find
questions by subject, difficulty and whether they are live, switch one off without deleting it, and be stopped from
saving a broken one.

Use cases:
- the model is registered, with filters for subject, band and active
- the list shows what identifies a question (subject, level, band, active) and can be searched by its text
- a superuser can open the list and the change form
- saving a broken question from the admin is refused with the model's message
"""

import pytest
from django.contrib import admin
from django.urls import reverse

from marketing.models import DemoQuestion

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client, django_user_model):
    user = django_user_model.objects.create_superuser("root@example.com", password="x", name="Root")
    client.force_login(user)
    return client


def test_the_model_is_registered_with_the_filters_that_help():
    model_admin = admin.site._registry[DemoQuestion]

    assert set(model_admin.list_filter) == {"subject", "band", "is_active"}
    assert {"subject", "level_label", "band", "is_active"} <= set(model_admin.list_display)
    assert "question" in model_admin.search_fields


def test_a_superuser_can_open_the_list_and_a_form(staff):
    first = DemoQuestion.objects.first()

    assert staff.get(reverse("admin:marketing_demoquestion_changelist"), {"band": "1"}).status_code == 200
    assert staff.get(reverse("admin:marketing_demoquestion_change", args=[first.pk])).status_code == 200


def test_a_broken_question_is_refused_in_the_admin(staff):
    first = DemoQuestion.objects.first()
    data = {
        "subject": first.subject,
        "level_label": first.level_label,
        "band": first.band,
        "question": first.question,
        "options": '["only", "two"]',
        "correct_index": 0,
        "outcome_right": '{"level": 3, "level_label": "x", "lesson_start": "y"}',
        "outcome_wrong": '{"level": 2, "level_label": "x", "lesson_start": "y"}',
        "is_active": "on",
    }

    response = staff.post(reverse("admin:marketing_demoquestion_change", args=[first.pk]), data)

    assert response.status_code == 200  # the form again, with the error
    assert "exactly three" in response.content.decode()
    first.refresh_from_db()
    assert len(first.options) == 3
