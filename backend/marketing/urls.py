from django.urls import path

from . import views

urlpatterns = [
    path("landing/demo-question", views.DemoQuestionView.as_view(), name="landing-demo-question"),
    path("public/testimonials", views.PublicTestimonialsView.as_view(), name="public-testimonials"),
    path("public/pricing", views.PublicPricingView.as_view(), name="public-pricing"),
]
