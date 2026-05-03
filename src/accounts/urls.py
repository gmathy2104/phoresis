"""URL config for accounts — login, logout, profile."""

from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.PhoresisLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("theme/", views.theme_set_view, name="theme_set"),
]
