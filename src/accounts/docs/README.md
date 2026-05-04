# `accounts`

User authentication, profile, and group permissions.

## Purpose

- Custom `User` model (`AbstractUser` + a friendlier `__str__`).
- `UserProfile` for theme / language / avatar / job_title (one-to-one with User).
- Three seeded groups: Lab User, Reviewer, Admin.
- Login / logout / profile views.
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

## Key files

| File | Purpose |
|---|---|
| `models.py` | User + UserProfile |
| `signals.py` | post_save → auto-create UserProfile |
| `views.py` | LoginView, profile_view, theme_set_view |
| `permissions.py` | group helpers |
| `migrations/0002_seed_groups.py` | data migration seeding the 3 groups |
| `management/commands/seed_groups.py` | re-seed command (idempotent) |

## Integration

- The `request.user.profile.theme` value is read by `base.html` to set the initial `data-theme` attribute on `<html>`, avoiding the dark/light flash on load.
- `LOGIN_REDIRECT_URL = "dashboard:home"` — non-namespaced (lazy resolve), so adding/renaming the dashboard route doesn't require an account migration.
