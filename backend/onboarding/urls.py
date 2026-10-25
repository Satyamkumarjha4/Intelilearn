from django.urls import path

from . import views

urlpatterns = [
    path("onboarding/topic-suggestions", views.TopicSuggestionsView.as_view(), name="onboarding-topic-suggestions"),
]
