import pytest

pytestmark = pytest.mark.django_db

ONBOARDING = {
    "education_level": "undergraduate",
    "grade_or_year": "2nd year B.Tech",
    "field_of_study": "Computer Science",
    "preferred_language": "en",
    "learning_preference": "hands_on",
    "goal": "exam_prep",
    "notes": "I know arrays already.",
}


def test_profile_requires_authentication(api_client):
    assert api_client.get("/api/profile").status_code == 401


def test_new_profile_is_incomplete(signed_in_client):
    body = signed_in_client.get("/api/profile").json()

    assert body["email"] == "ada@example.com"
    assert body["name"] == "Ada Lovelace"
    assert body["preferred_language"] == "en"
    assert body["profile_complete"] is False


def test_onboarding_completes_profile_and_sets_marker(signed_in_client):
    response = signed_in_client.put("/api/profile", ONBOARDING, format="json")

    assert response.status_code == 200
    assert response.json()["profile_complete"] is True
    assert response.cookies["lc_onboarded"].value == "1"
    assert signed_in_client.get("/api/auth/me").json()["profile_complete"] is True


def test_login_after_onboarding_sets_onboarded_marker(signed_in_client, user):
    signed_in_client.put("/api/profile", ONBOARDING, format="json")
    signed_in_client.post("/api/auth/logout")

    response = signed_in_client.post(
        "/api/auth/login", {"email": user.email, "password": "correct-horse-battery-staple"}
    )

    assert response.cookies["lc_onboarded"].value == "1"


def test_put_requires_onboarding_fields(signed_in_client):
    incomplete = {k: v for k, v in ONBOARDING.items() if k != "goal"}

    response = signed_in_client.put("/api/profile", incomplete, format="json")

    assert response.status_code == 400
    assert "goal" in response.json()["fields"]


def test_put_rejects_unknown_choice(signed_in_client):
    response = signed_in_client.put("/api/profile", {**ONBOARDING, "learning_preference": "osmosis"}, format="json")

    assert response.status_code == 400
    assert response.json()["fields"]["learning_preference"] == ["Please choose one of the options."]


def test_empty_select_gets_a_readable_message(signed_in_client):
    response = signed_in_client.put("/api/profile", {**ONBOARDING, "goal": ""}, format="json")

    assert response.json()["fields"]["goal"] == ["Please choose one of the options."]


def test_patch_updates_name_but_not_email(signed_in_client, user):
    response = signed_in_client.patch("/api/profile", {"name": "Countess Ada", "email": "x@y.z"}, format="json")

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.name == "Countess Ada"
    assert user.email == "ada@example.com"
