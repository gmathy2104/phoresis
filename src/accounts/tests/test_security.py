"""Sign-in hardening: lockout after failed logins, two-factor, password rules."""

from __future__ import annotations

import base64

import pytest
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from django.core.management import call_command
from django.test import Client, RequestFactory
from django.urls import reverse

from accounts.security import axes_username, client_ip
from accounts.tests.factories import UserFactory

LOGIN = reverse("accounts:login")
SETUP = reverse("accounts:two_factor_setup")
VERIFY = reverse("accounts:two_factor_verify")
PROFILE = reverse("accounts:profile")
HOME = reverse("dashboard:home")
API = "/api/search/?q=x"


def _code(device: TOTPDevice) -> str:
    """The code an authenticator app would show for this device right now."""
    return f"{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits, drift=device.drift):06d}"


def _fresh(device: TOTPDevice) -> None:
    """Let the current code be used again (a real user would wait for the next 30 s window)."""
    TOTPDevice.objects.filter(pk=device.pk).update(last_t=-1, throttling_failure_count=0)


def _enroll(client: Client, user) -> tuple[TOTPDevice, list[str]]:
    """Run the setup page as `user` (already signed in) and return the device and backup codes."""
    client.get(SETUP)
    device = TOTPDevice.objects.get(user=user)
    response = client.post(SETUP, {"token": _code(device)})
    assert response.status_code == 200
    device.refresh_from_db()
    _fresh(device)
    return device, list(response.context["codes"])


def _bad_login(client: Client, username: str, **extra):
    return client.post(LOGIN, {"username": username, "password": "wrong"}, **extra)


# ── lockout ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def lockout(settings):
    settings.AXES_ENABLED = True
    return settings


@pytest.mark.django_db
def test_five_wrong_passwords_lock_the_account_even_for_the_right_one(client, lockout) -> None:
    UserFactory(username="mia")
    for _ in range(4):
        assert _bad_login(client, "mia").status_code == 200
    assert _bad_login(client, "mia").status_code == 429

    response = client.post(LOGIN, {"username": "mia", "password": "test-pwd"})
    assert response.status_code == 429
    assert b"Too many attempts" in response.content
    assert b"15 minutes" in response.content
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_email_and_case_variants_share_one_counter(client, lockout) -> None:
    UserFactory(username="noa", email="noa@example.com")
    for typed in ("noa", "NOA", "noa@example.com", "Noa@Example.com", " noa "):
        _bad_login(client, typed)
    assert client.post(LOGIN, {"username": "noa", "password": "test-pwd"}).status_code == 429


@pytest.mark.django_db
def test_lockout_is_per_account_and_per_address(client, lockout) -> None:
    UserFactory(username="olga")
    UserFactory(username="paul")
    for _ in range(5):
        _bad_login(client, "olga", HTTP_X_FORWARDED_FOR="192.168.1.20")

    # Another account from the same address, and the same account from another address, still sign in.
    assert (
        client.post(
            LOGIN, {"username": "paul", "password": "test-pwd"}, HTTP_X_FORWARDED_FOR="192.168.1.20"
        ).status_code
        == 302
    )
    assert (
        Client()
        .post(LOGIN, {"username": "olga", "password": "test-pwd"}, HTTP_X_FORWARDED_FOR="192.168.1.21")
        .status_code
        == 302
    )
    assert (
        Client()
        .post(LOGIN, {"username": "olga", "password": "test-pwd"}, HTTP_X_FORWARDED_FOR="192.168.1.20")
        .status_code
        == 429
    )


def test_client_ip_reads_what_the_proxy_appended() -> None:
    rf = RequestFactory()
    # From Caddy (loopback / Docker bridge): the last entry, which Caddy wrote.
    assert client_ip(rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="192.168.1.20")) == "192.168.1.20"
    assert (
        client_ip(rf.get("/", REMOTE_ADDR="172.18.0.3", HTTP_X_FORWARDED_FOR="6.6.6.6, 192.168.1.20")) == "192.168.1.20"
    )
    # Not from a proxy: the header is the client's own claim and is ignored.
    assert client_ip(rf.get("/", REMOTE_ADDR="8.8.8.8", HTTP_X_FORWARDED_FOR="192.168.1.20")) == "8.8.8.8"
    # Garbage in the header: fall back to the connection's address.
    assert client_ip(rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="nonsense")) == "127.0.0.1"
    assert client_ip(rf.get("/", REMOTE_ADDR="127.0.0.1")) == "127.0.0.1"


@pytest.mark.django_db
def test_axes_username_resolves_an_email_to_its_account() -> None:
    UserFactory(username="Quinn", email="q@example.com")
    assert axes_username(None, {"username": "Q@Example.com"}) == "quinn"
    assert axes_username(None, {"username": "Ghost"}) == "ghost"
    assert axes_username(None, {}) == ""


# ── two-factor ──────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_without_two_factor_nothing_changes(client) -> None:
    client.force_login(UserFactory(username="rita"))
    assert client.get(PROFILE).status_code == 200
    assert b"Two-factor off" in client.get(PROFILE).content


@pytest.mark.django_db
def test_setup_shows_the_key_then_turns_two_factor_on_with_backup_codes(client) -> None:
    user = UserFactory(username="sam")
    client.force_login(user)

    page = client.get(SETUP)
    assert page.status_code == 200
    device = TOTPDevice.objects.get(user=user)
    assert not device.confirmed
    assert base64.b32encode(device.bin_key).decode()[:4].encode() in page.content
    assert b"<svg" in page.content

    assert b"not valid" in client.post(SETUP, {"token": "000000"}).content
    _fresh(device)

    done = client.post(SETUP, {"token": _code(device)})
    assert len(done.context["codes"]) == 10
    device.refresh_from_db()
    assert device.confirmed
    # The session that did the setup is verified: no code asked right after.
    assert client.get(PROFILE).status_code == 200
    assert b"Two-factor on" in client.get(PROFILE).content
    assert b"10 backup codes left" in client.get(PROFILE).content


@pytest.mark.django_db
def test_password_alone_opens_nothing_once_two_factor_is_on(client) -> None:
    user = UserFactory(username="tess")
    client.force_login(user)
    device, _ = _enroll(client, user)

    fresh = Client()
    assert fresh.post(LOGIN, {"username": "tess", "password": "test-pwd"}).status_code == 302

    page = fresh.get(PROFILE)
    assert page.status_code == 302
    assert page.url == f"{VERIFY}?next=%2Faccounts%2Fprofile%2F"
    api = fresh.get(API)
    assert api.status_code == 403
    assert api.json()["code"] == "two_factor_required"
    htmx = fresh.get(HOME, HTTP_HX_REQUEST="true")
    assert htmx.status_code == 403
    assert htmx["HX-Redirect"] == VERIFY
    assert fresh.post(reverse("accounts:theme_set"), {"theme": "dark"}).status_code == 302
    # The setup page must not let a password-only session add a device of its own.
    assert fresh.get(SETUP).status_code == 302
    assert TOTPDevice.objects.filter(user=user).count() == 1
    assert fresh.get("/admin/").status_code == 302

    assert b"not valid" in fresh.post(VERIFY, {"token": "000000"}).content
    _fresh(device)
    ok = fresh.post(VERIFY, {"token": _code(device), "next": PROFILE})
    assert ok.status_code == 302
    assert ok.url == PROFILE
    assert fresh.get(PROFILE).status_code == 200
    assert fresh.get(API).status_code == 200


@pytest.mark.django_db
def test_verify_ignores_a_next_url_on_another_site(client) -> None:
    user = UserFactory(username="uma")
    client.force_login(user)
    device, _ = _enroll(client, user)
    fresh = Client()
    fresh.post(LOGIN, {"username": "uma", "password": "test-pwd"})
    response = fresh.post(VERIFY, {"token": _code(device), "next": "https://evil.example/"})
    assert response.url == HOME


@pytest.mark.django_db
def test_a_backup_code_works_once(client) -> None:
    user = UserFactory(username="vera")
    client.force_login(user)
    _, codes = _enroll(client, user)

    first = Client()
    first.post(LOGIN, {"username": "vera", "password": "test-pwd"})
    assert first.post(VERIFY, {"token": f" {codes[0].upper()} "}).url == PROFILE
    assert b"9 backup codes left" in first.get(PROFILE).content

    second = Client()
    second.post(LOGIN, {"username": "vera", "password": "test-pwd"})
    assert second.post(VERIFY, {"token": codes[0]}).status_code == 200
    assert second.get(PROFILE).status_code == 302


@pytest.mark.django_db
def test_new_backup_codes_replace_the_old_ones(client) -> None:
    user = UserFactory(username="walt")
    client.force_login(user)
    _, old = _enroll(client, user)
    response = client.post(reverse("accounts:two_factor_backup_codes"))
    new = response.context["codes"]
    assert len(new) == 10
    assert not set(new) & set(old)
    assert set(StaticToken.objects.filter(device__user=user).values_list("token", flat=True)) == set(new)


@pytest.mark.django_db
def test_turning_off_needs_the_password(client) -> None:
    user = UserFactory(username="xena")
    client.force_login(user)
    _enroll(client, user)
    disable = reverse("accounts:two_factor_disable")

    assert client.post(disable, {"password": "nope"}).url.endswith("?two_factor=wrong-password")
    assert TOTPDevice.objects.filter(user=user, confirmed=True).exists()

    assert client.post(disable, {"password": "test-pwd"}).url.endswith("?two_factor=off")
    assert not TOTPDevice.objects.filter(user=user).exists()
    assert not StaticToken.objects.filter(device__user=user).exists()
    assert client.get(PROFILE).status_code == 200


@pytest.mark.django_db
def test_required_for_staff_sends_them_to_setup_and_cannot_be_turned_off(client, settings) -> None:
    settings.PHORESIS_REQUIRE_2FA = "staff"
    staff = UserFactory(username="yan", is_staff=True)
    client.force_login(staff)

    page = client.get(HOME)
    assert page.status_code == 302
    assert page.url.startswith(SETUP)
    assert client.get(API).status_code == 403
    assert client.get(SETUP).status_code == 200

    _enroll(client, staff)
    assert client.get(PROFILE).status_code == 200
    assert b"cannot be turned off" in client.get(PROFILE).content
    client.post(reverse("accounts:two_factor_disable"), {"password": "test-pwd"})
    assert TOTPDevice.objects.filter(user=staff, confirmed=True).exists()

    # A non-staff account is left alone in this mode, and caught by "all".
    other = Client()
    other.force_login(UserFactory(username="zoe"))
    assert other.get(PROFILE).status_code == 200
    settings.PHORESIS_REQUIRE_2FA = "all"
    assert other.get(PROFILE).status_code == 302


@pytest.mark.django_db
def test_reset_command_lets_a_user_back_in(client) -> None:
    user = UserFactory(username="abel", email="abel@example.com")
    client.force_login(user)
    _enroll(client, user)

    call_command("reset_two_factor", "ABEL@example.com")
    assert not TOTPDevice.objects.filter(user=user).exists()
    fresh = Client()
    fresh.post(LOGIN, {"username": "abel", "password": "test-pwd"})
    assert fresh.get(PROFILE).status_code == 200


@pytest.mark.django_db
def test_api_refuses_http_basic(client) -> None:
    """A password in an Authorization header is not a way in: it would skip the second factor."""
    UserFactory(username="bea")
    header = "Basic " + base64.b64encode(b"bea:test-pwd").decode()
    response = client.get("/api/v1/images/", HTTP_AUTHORIZATION=header)
    assert response.status_code == 403


# ── passwords ───────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_password_change_applies_the_rules(client) -> None:
    user = UserFactory(username="carl")
    client.force_login(user)
    url = reverse("accounts:password_change")
    assert client.get(url).status_code == 200

    for weak in ("short1!", "123456789012345", "password1234"):
        response = client.post(url, {"old_password": "test-pwd", "new_password1": weak, "new_password2": weak})
        assert response.status_code == 200, weak
        user.refresh_from_db()
        assert user.check_password("test-pwd"), weak

    strong = "plasmid-ladder-gel-42"
    response = client.post(url, {"old_password": "test-pwd", "new_password1": strong, "new_password2": strong})
    assert response.status_code == 302
    assert response.url == f"{PROFILE}?password=changed"
    user.refresh_from_db()
    assert user.check_password(strong)
    assert b"Password changed" in client.get(response.url).content


@pytest.mark.django_db
class TestMediaAuth:
    """What Caddy asks before serving a file under /media/."""

    URL = "/api/auth/media/"

    def test_no_session_is_refused(self, client):
        assert client.get(self.URL).status_code == 401

    def test_signed_in_session_is_let_through(self, client):
        client.force_login(UserFactory())
        response = client.get(self.URL)
        assert response.status_code == 204
        assert response.content == b""

    def test_session_owing_its_second_factor_is_refused(self, client):
        user = UserFactory()
        TOTPDevice.objects.create(user=user, name="Authenticator app", confirmed=True)
        client.force_login(user)
        assert client.get(self.URL).status_code == 403
