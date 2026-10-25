from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

admin.site.site_header = "Socra admin"
admin.site.site_title = "Socra admin"
admin.site.index_title = "Socra admin"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("core.urls")),
    path("api/", include("accounts.urls")),
    path("api/", include("lessons.urls")),
    path("api/", include("onboarding.urls")),
    path("api/", include("marketing.urls")),
    path("api/console/", include("console.urls")),
    # OpenAPI schema + docs
    path("api/schema", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
