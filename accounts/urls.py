from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views
from .forms import LendMateAuthenticationForm

app_name = "accounts"

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html",
            authentication_form=LendMateAuthenticationForm,
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    # Logout is POST-only (Django 5+), triggered from a CSRF-protected form.
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password/change/", views.LendMatePasswordChangeView.as_view(), name="password_change"),
    path(
        "password/reset/",
        auth_views.PasswordResetView.as_view(success_url=reverse_lazy("accounts:password_reset_done")),
        name="password_reset",
    ),
    path(
        "password/reset/sent/",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "password/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            success_url=reverse_lazy("accounts:password_reset_complete")
        ),
        name="password_reset_confirm",
    ),
    path(
        "password/reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
]
