"""Unit under test: `GET /api/profile/options` (`accounts.options.ProfileOptions`), the choice lists of the profile.

Why: the frontend used to hard-code the education levels, goals, learning styles and languages, so a choice added in
the backend never showed up (and one removed still did). The API is now the single source: what the options endpoint
offers is exactly what the profile accepts, and the sign-up screens can read it before anyone has an account.

Use cases:
- the options need no sign-in
- every choice list of the profile is there, as value and label, in the model's order
- every value offered is accepted by the profile, and an unlisted one is refused
- the languages are English, Hindi, Spanish, French and German
- a language outside the list, or a note longer than 2000 characters, is refused by the profile
"""

import pytest

from accounts.models import Profile

pytestmark = pytest.mark.django_db

ONBOARDING = {
    "education_level": "undergraduate",
    "grade_or_year": "2nd year B.Tech",
    "field_of_study": "Computer Science",
    "preferred_language": "en",
    "learning_preference": "hands_on",
    "goal": "exam_prep",
}


def options(client):
    response = client.get("/api/profile/options")
    assert response.status_code == 200
    return response.json()


def test_options_need_no_sign_in(api_client):
    assert api_client.get("/api/profile/options").status_code == 200


def test_every_choice_list_is_offered_as_value_and_label(api_client):
    body = options(api_client)

    assert set(body) == {"education_level", "learning_preference", "goal", "preferred_language"}
    for field, choices in {
        "education_level": Profile.EducationLevel.choices,
        "learning_preference": Profile.LearningPreference.choices,
        "goal": Profile.Goal.choices,
        "preferred_language": Profile.PreferredLanguage.choices,
    }.items():
        assert body[field] == [{"value": value, "label": str(label)} for value, label in choices]


def test_languages_are_the_five_the_product_writes_in(api_client):
    languages = options(api_client)["preferred_language"]

    assert [item["value"] for item in languages] == ["en", "hi", "es", "fr", "de"]
    assert languages[0]["label"] == "English"


def test_every_value_offered_is_accepted_by_the_profile(signed_in_client):
    body = options(signed_in_client)
    for field in body:
        for item in body[field]:
            response = signed_in_client.put("/api/profile", {**ONBOARDING, field: item["value"]}, format="json")

            assert response.status_code == 200, (field, item["value"], response.json())


def test_a_language_outside_the_list_is_refused(signed_in_client):
    response = signed_in_client.put("/api/profile", {**ONBOARDING, "preferred_language": "tlh"}, format="json")

    assert response.status_code == 400
    assert "preferred_language" in response.json()["fields"]


def test_notes_are_limited_to_2000_characters(signed_in_client):
    assert signed_in_client.patch("/api/profile", {"notes": "x" * 2000}, format="json").status_code == 200

    response = signed_in_client.patch("/api/profile", {"notes": "x" * 2001}, format="json")

    assert response.status_code == 400
    assert "notes" in response.json()["fields"]
