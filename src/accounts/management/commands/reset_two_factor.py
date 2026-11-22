"""Remove a user's second factor: the way back in when the phone AND the backup codes are lost.

    manage.py reset_two_factor <username-or-email>

The user signs in with the password alone afterwards and, where two-factor is required
(PHORESIS_REQUIRE_2FA), is taken straight to the setup page. Failed-login lockouts are a different
thing: `manage.py axes_reset_username <username>`.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from accounts.two_factor import remove_two_factor


class Command(BaseCommand):
    help = "Remove the authenticator app and backup codes of one user."

    def add_arguments(self, parser):
        parser.add_argument("user", help="Username or email of the account")

    def handle(self, *args, **options):
        ident = options["user"].strip()
        users = list(get_user_model().objects.filter(Q(username=ident) | Q(email__iexact=ident)))
        if len(users) != 1:
            raise CommandError(f"{len(users)} accounts match {ident!r}; expected exactly one.")
        user = users[0]
        removed = remove_two_factor(user)
        if removed:
            self.stdout.write(self.style.SUCCESS(f"Two-factor removed for {user.username}."))
        else:
            self.stdout.write(f"{user.username} had no two-factor set up; nothing to do.")
