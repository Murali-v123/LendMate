from django.contrib import admin
from django.urls import include, path
from django.http import JsonResponse


def health_check(request):
    """Simple health-check endpoint for Railway and load-balancers."""
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("", include("core.urls")),
    path("lending/", include("lending.urls")),
    path("", include("notifications.urls")),
    path("health/", health_check, name="health_check"),
]
