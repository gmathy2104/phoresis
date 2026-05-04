"""Group-based permission helpers for accounts."""

from django.contrib.auth.models import AbstractUser

GROUP_LAB_USER = "Lab User"
GROUP_REVIEWER = "Reviewer"
GROUP_ADMIN = "Admin"

ALL_GROUPS = (GROUP_LAB_USER, GROUP_REVIEWER, GROUP_ADMIN)


def _in_group(user: AbstractUser, name: str) -> bool:
    return user.is_authenticated and (user.is_superuser or user.groups.filter(name=name).exists())


def is_admin(user: AbstractUser) -> bool:
    return _in_group(user, GROUP_ADMIN)


def is_reviewer(user: AbstractUser) -> bool:
    return _in_group(user, GROUP_REVIEWER) or is_admin(user)


def is_lab_user(user: AbstractUser) -> bool:
    return _in_group(user, GROUP_LAB_USER) or is_reviewer(user) or is_admin(user)
