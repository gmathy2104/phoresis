"""User and UserProfile models for Phoresis.

`AUTH_USER_MODEL = "accounts.User"` is set in `phoresis.settings.base` so this
custom user is the project's user model from day one — avoiding the painful
mid-project swap that Django warns about.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Phoresis user — `AbstractUser` + a friendlier `__str__`."""

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["first_name", "last_name", "username"]

    def __str__(self) -> str:
        full = self.get_full_name().strip()
        return full or self.username


class UserProfile(models.Model):
    """Per-user UI preferences and metadata.

    Created automatically via `accounts.signals.create_user_profile` whenever a
    `User` is created, so `user.profile` is always safe to access.
    """

    THEME_AUTO = "auto"
    THEME_LIGHT = "light"
    THEME_DARK = "dark"
    THEME_CHOICES = [
        (THEME_AUTO, "Auto"),
        (THEME_LIGHT, "Light"),
        (THEME_DARK, "Dark"),
    ]

    LANG_EN = "en"
    LANG_FR = "fr"
    LANG_CHOICES = [
        (LANG_EN, "English"),
        (LANG_FR, "Français"),
    ]

    user = models.OneToOneField("accounts.User", on_delete=models.CASCADE, related_name="profile")
    theme = models.CharField(max_length=10, choices=THEME_CHOICES, default=THEME_AUTO)
    language = models.CharField(max_length=2, choices=LANG_CHOICES, default=LANG_EN)
    avatar = models.ImageField(upload_to="accounts/avatars/", blank=True, null=True)
    job_title = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User profile"
        verbose_name_plural = "User profiles"

    def __str__(self) -> str:
        return f"{self.user} — profile"
