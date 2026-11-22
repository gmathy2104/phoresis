"""URL config for accounts — login, logout, profile, password, two-factor."""

from django.contrib.auth.views import LogoutView
from django.urls import path

from . import two_factor, views

app_name = "accounts"

urlpatterns = [
    path("login/", views.PhoresisLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("theme/", views.theme_set_view, name="theme_set"),
    path("password/", views.PhoresisPasswordChangeView.as_view(), name="password_change"),
    path("two-factor/setup/", two_factor.setup_view, name="two_factor_setup"),
    path("two-factor/verify/", two_factor.verify_view, name="two_factor_verify"),
    path("two-factor/backup-codes/", two_factor.backup_codes_view, name="two_factor_backup_codes"),
    path("two-factor/disable/", two_factor.disable_view, name="two_factor_disable"),
]
