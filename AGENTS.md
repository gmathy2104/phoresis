# Project agents brief — Phoresis

This file is read at the start of every Claude / Cursor / Aider session.
It captures non-negotiable project policies that override default LLM behavior.

## 1. NO CDN. Static assets are ALWAYS self-hosted.

Phoresis is a **self-hosted Django app** for biology labs. Many of those labs:

- have corporate firewalls blocking external CDNs (unpkg, jsdelivr, cdnjs, ...);
- run on networks with strict tracking-prevention policies (Edge, Firefox Strict,
  Safari ITP) that **block third-party storage and sometimes scripts**;
- expect to keep working when the lab loses internet (air-gapped equipment).

Therefore, every JS / CSS / icon / font / WASM dependency is downloaded once,
checked into `src/<app>/static/<app>/{js,css,fonts}/vendor/`, and served by
WhiteNoise + Caddy at `https://phoresis/static/...`. Templates reference them
via Django's `{% static %}` tag so WhiteNoise's manifest hash is applied for
cache-busting.

**Concrete consequences for any change you make:**

- Never write `<script src="https://unpkg.com/...">` or any CDN URL in a
  template, JS file, or CSS `@import`.
- New dependency? Download it into the right `vendor/` folder, commit it to
  the repo, reference it via `{% static 'app/js/vendor/<name>.min.js' %}`.
- For dynamic ES-module `import()` calls in JS, expose the static URL through
  `window.PHORESIS_URLS.<key>` in `base.html` so the manifest hash applies
  (CompressedManifestStaticFilesStorage rejects the unhashed filename).
- For Tailwind / PostCSS plugins, add them to `package.json` and run
  `npm run build:css` -- output ends up in
  `src/phoresis_ui/static/phoresis_ui/css/output.css`.
- Already-vendored:
  - `phoresis_ui/js/vendor/htmx-2.0.3.min.js`
  - `phoresis_ui/js/vendor/alpine-3.14.3.min.js`
  - `phoresis_ui/js/vendor/countup-2.8.0.min.js`
  - `gel_analyzer/js/vendor/svg.min.js`
  - Lucide icons sprite at `phoresis_ui/icons/lucide-sprite.svg`

If you find a remaining CDN URL anywhere in `src/`, it's a bug. Vendor it.

## 2. Django comment syntax

`{# ... #}` is **single-line only** in Django templates. The moment you put
a newline inside, the parser stops treating it as a comment and renders the
WHOLE block as visible text in the browser. Multi-line comments REQUIRE
`{% comment %} ... {% endcomment %}`.

Quick check before committing: if your `{# ... #}` spans more than one line,
it's broken. We've shipped this bug twice (v1.0.29 -> v1.0.31, v1.0.34 ->
v1.0.35). Don't make it three.

## 3. Defensive coding for browser storage

Always wrap `localStorage` / `sessionStorage` access in `try/catch`. Edge's
"Tracking Prevention", Safari "Lockdown", Firefox "Strict", and private
windows can throw `SecurityError` on either read OR write. An unguarded
access inside `alpine:init` aborts the whole listener and breaks every
`$store.*` on the page (we hit this in v1.0.31).

`src/phoresis_ui/static/phoresis_ui/js/alpine-init.js` has reference helpers
(`safeLocalGet` / `safeLocalSet`) to copy the pattern from.

## 4. Settings: env-overridable in production

Anything that points at a writable filesystem path (STATIC_ROOT, MEDIA_ROOT,
log dirs, ML model dirs, ...) must be readable from `os.environ` with a
sensible local-dev fallback. Hardcoding `BASE_DIR / "X"` is a permission-denied
bomb the moment the container runs as a non-root user against a read-only
WORKDIR (we hit this in v1.0.18).

For ML model paths: anchor on `SRC_DIR` (`= BASE_DIR / "src"`), not
`BASE_DIR`, because source is COPY'd to `/app/src/...` in the Docker image.

## 5. Reverse proxy + Caddy

Production runs behind Caddy 2 at `https://phoresis`, with active health
probes against the upstream `web:8000`. That means:

- `ALLOWED_HOSTS` must include `web` (the Docker service name) on top of
  whatever public hosts the operator configured.
- `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` is
  required, otherwise `SESSION_COOKIE_SECURE=True` strips the cookie on
  every login response.
- `CSRF_TRUSTED_ORIGINS` must include the public origin(s); without it
  every POST returns 403.

## 6. Container init order

Web container entrypoint runs in this order, per spec §10.3:
`migrate -> collectstatic --clear --ignore "input.css" --ignore "tokens.css"
-> seed_groups -> seed_ladder_templates -> create_initial_users --from-env
--skip-existing -> exec gunicorn`. The `--ignore` flags are required because
WhiteNoise's manifest backend tries to post-process the Tailwind source CSS
otherwise. The `--skip-existing` for `create_initial_users` is intentional;
the same flag for `seed_ladder_templates` does NOT exist (the command is
already idempotent via `update_or_create`).

## 7. Login UX

Custom auth backend at `accounts.backends.EmailOrUsernameModelBackend`
accepts BOTH email and username (case-insensitive on email). install.ps1
asks the operator for an email; `create_initial_users` derives username
from the local part. Users naturally try logging in with the email they
entered, so the backend has to honour both.

## 8. Compose env-file resolution

The `.env` file lives at the **project root** (`<repo>/.env`), but the
compose file is at `docker/docker-compose.yml`. By default, compose v2
looks for `.env` in the directory of the compose file, NOT the project
root -- which means `${PHORESIS_MEDIA_DIR}` and friends silently fall
back to their default values when an operator runs `docker compose ...`
ad-hoc. The Caddy media-mount silently breaking is the canonical bite
(v1.0.36).

Two safeguards in place:

1. `compose.yml` uses `${VAR:?error message}` instead of `${VAR:-default}`
   for path-resolution variables. A missing `PHORESIS_MEDIA_DIR` now
   fails fast instead of mounting the wrong directory.

2. `scripts/phoresis.ps1` is a thin wrapper that always passes
   `--env-file <root>/.env` and `-f docker/docker-compose.yml`. Tell
   users to invoke that for ad-hoc operations rather than raw
   `docker compose`. (Background scripts like `install.ps1`,
   `update.ps1` do their own --env-file plumbing via `_common.ps1`.)

## 9. PowerShell compatibility

`scripts/*.ps1` MUST run on Windows PowerShell 5.1 (the default on Windows
Server / older Windows boxes), not just PS7+. That means:

- No ASCII-incompatible characters in source files (em-dashes, smart quotes).
  Default Windows console codepage is CP1252 on French / German systems --
  UTF-8 BOM characters in PS5.1 fail to parse.
- No `Invoke-WebRequest -SkipCertificateCheck` (PS7+ only). Use `curl.exe`
  (ships with Windows 10 build 17063+) instead -- it brings its own TLS
  stack and accepts `-k`.
- `curl -o $null` does NOT discard output on Windows (`$null` PowerShell
  variable expands to empty string; curl writes body to stdout). Use
  `curl -o NUL` (the Windows null device).

## 10. Direct-to-main pushes

The user authorized direct pushes to `main` for the v1.0.x bug-hunt cycle
("fix directement dans le main hein"). For v1.1.x onward, prefer PRs unless
explicitly told otherwise.
