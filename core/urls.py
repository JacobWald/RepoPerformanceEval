from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),

    # Django auth: /accounts/login/, /accounts/logout/, password reset, etc.
    path("accounts/", include("django.contrib.auth.urls")),

    # Your app routes (landing signup + home)
    path("", include("analytics.urls")),
]


