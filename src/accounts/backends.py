"""Authentication backends for Phoresis.

The default Django ModelBackend matches against `USERNAME_FIELD` only (which is
`username` for our `AbstractUser`-derived model). But install.ps1 prompts the
operator for an *email* and `create_initial_users` derives the username from
the email's local part (e.g. `gregory.mathy@outlook.com` -> `gregory.mathy`),
so users naturally try to log in with the email they remember -- and fail.

`EmailOrUsernameModelBackend` accepts either, removing the foot-gun. It tries
`email__iexact` first (case-insensitive, since email is supposed to be
case-insensitive per RFC 5321 §2.4 for the local part in practice), then falls
back to the regular username lookup.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameModelBackend(ModelBackend):
    """Authenticate by email (case-insensitive) OR username.

    Drop-in replacement for django.contrib.auth.backends.ModelBackend.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):  # noqa: D401
        if username is None or password is None:
            return None

        UserModel = get_user_model()
        try:
            # Try email first -- that's what install.ps1 asks the operator for.
            user = UserModel.objects.get(email__iexact=username)
        except UserModel.DoesNotExist:
            try:
                user = UserModel.objects.get(**{UserModel.USERNAME_FIELD: username})
            except UserModel.DoesNotExist:
                # Run the default password hasher anyway to mitigate timing
                # attacks (mirrors ModelBackend's own behavior).
                UserModel().set_password(password)
                return None
        except UserModel.MultipleObjectsReturned:
            # Two users with the same email (shouldn't happen with our schema,
            # but guard against it) -- bail out, force the operator to pick.
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
