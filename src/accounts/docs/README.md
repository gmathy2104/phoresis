# `accounts`

User authentication, profile, and group permissions.

## Purpose

- Custom `User` model (`AbstractUser` + a friendlier `__str__`).
- `UserProfile` for theme / language / avatar / job_title (one-to-one with User).
- Three seeded groups: Lab User, Reviewer, Admin.
- Login / logout / profile views.
- Sign-in security: lockout after failed logins, two-factor (TOTP), password rules.
- Theme persistence endpoint (`POST /accounts/theme/`).

## Public surface

### Settings
- `AUTH_USER_MODEL = "accounts.User"` — set in `phoresis.settings.base`.
- `LOGIN_URL = "accounts:login"`.
- `LOGIN_REDIRECT_URL = "dashboard:home"`.

### Permission helpers
- `from accounts.permissions import is_lab_user, is_reviewer, is_admin`
- `from accounts.permissions import GROUP_LAB_USER, GROUP_REVIEWER, GROUP_ADMIN, ALL_GROUPS`

### Management commands
- `python manage.py seed_groups` — idempotent; re-creates the 3 groups if missing.
- `python manage.py create_initial_users --from-env --skip-existing` — used by `entrypoint.sh` (lives in `gel_analyzer.management.commands` historically).

## Sign-in security

Three protections, on every install (Windows / Docker and Mac):

- **Lockout** (django-axes). 5 wrong passwords for one account from one address pause that pair for
  15 minutes; the right password is refused too until then (`accounts/locked.html`, HTTP 429).
  Counted per (account, address), never per address alone: behind Docker Desktop every browser has
  the gateway's address. Email or username, any case, land on the same counter
  (`security.axes_username`); the address is the one Caddy appended to `X-Forwarded-For`
  (`security.client_ip`). Tuning: `PHORESIS_LOGIN_FAILURE_LIMIT`, `PHORESIS_LOGIN_COOLOFF_MINUTES`.
  Lift a lockout: `manage.py axes_reset_username <username>` (or `axes_reset` for all).
- **Two-factor** (django-otp): a 6-digit code from an authenticator app (TOTP), plus 10 one-time
  backup codes. Anyone turns it on from the profile page. `PHORESIS_REQUIRE_2FA` says who must:
  `off` (default), `staff` (staff and superusers; what the Mac installer writes) or `all`. A required
  user without a device is taken to the setup page at sign-in and cannot turn it off.
  `middleware.TwoFactorMiddleware` holds back a session that has the password but not the code:
  pages redirect to the code page, `/api/` answers 403 `two_factor_required`, HTMX gets `HX-Redirect`.
  It covers the Django admin and the DRF API as well, which is why the API accepts the session only
  (no HTTP Basic). Phone and backup codes lost: `manage.py reset_two_factor <username-or-email>`.
- **Password rules** (`AUTH_PASSWORD_VALIDATORS`): 12 characters, not common, not numeric, not close
  to the name or email. Applied where a password is chosen in a form (`/accounts/password/`, admin).
  The first passwords written by the installers are not re-checked.

- **Media need a session.** Caddy serves `/media/` itself, but first asks Django
  (`forward_auth` to `/api/auth/media/`, `views.media_auth_view`): 204 with a signed-in session, 401
  without one, 403 while the second factor is owed. The check is in the Caddy configuration
  (`docker/Caddyfile`, `write_caddyfile` in `scripts/mac/phoresis.sh`): an install whose Caddyfile
  predates it still serves media to whoever has the URL. A Caddyfile that has the check in front of
  an image that predates the view refuses every media file (the view answers 404).

Tests never lock out (`AXES_ENABLED = False` in `settings.test`); `tests/test_security.py` turns it on.

## Key files

| File | Purpose |
|---|---|
| `models.py` | User + UserProfile |
| `signals.py` | post_save → auto-create UserProfile |
| `views.py` | LoginView, profile_view, theme_set_view, password change |
| `security.py` | who a failed login is counted against; who must use two-factor |
| `middleware.py` | holds back a session without its second factor |
| `two_factor.py` | setup (QR code), code at sign-in, backup codes, turn off |
| `management/commands/reset_two_factor.py` | operator's way back in for a user |
| `permissions.py` | group helpers |
| `migrations/0002_seed_groups.py` | data migration seeding the 3 groups |
| `management/commands/seed_groups.py` | re-seed command (idempotent) |

## Integration

- The `request.user.profile.theme` value is read by `base.html` to set the initial `data-theme` attribute on `<html>`, avoiding the dark/light flash on load.
- `LOGIN_REDIRECT_URL = "dashboard:home"` — non-namespaced (lazy resolve), so adding/renaming the dashboard route doesn't require an account migration.
