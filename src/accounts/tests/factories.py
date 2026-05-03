"""factory-boy factories for accounts tests."""

import factory

from django.contrib.auth.hashers import make_password

from accounts.models import User


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")
    first_name = "Test"
    last_name = "User"
    password = factory.LazyFunction(lambda: make_password("test-pwd"))
