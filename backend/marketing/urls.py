from django.urls import path

from . import views

urlpatterns = [
    path("landing/demo-question", views.DemoQuestionView.as_view(), name="landing-demo-question"),
]
