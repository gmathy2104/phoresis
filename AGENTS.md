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
  - `guided_tours/vendor/driverjs/1.10.2/` (Driver.js 1.10.2: `driver.js.iife.js`, `driver.css`, `LICENSE`)
  - `gel_analyzer/js/vendor/svg.min.js`
  - `gel_analyzer/js/vendor/d3.v7.min.js` (d3 7.9.0)
  - `gel_analyzer/js/vendor/plotly.min.js` (plotly.js 3.0.1)
  - `gel_analyzer/js/vendor/three/` (three.js 0.170.0: `three.module.min.js` + `addons/controls/OrbitControls.js`,
    mapped one file at a time in the page's import map -- `{% static %}` on a directory raises under the manifest storage)
  - `gel_analyzer/js/vendor/onnxruntime/` (ONNX Runtime Web 1.24.3: `ort.min.js`, its `.jsep.mjs` loader and the
    `.jsep.wasm` binary in Git LFS; the inference workers find the folder relative to their own URL)
  - Lucide icons sprite at `phoresis_ui/icons/lucide-sprite.svg`

If you find a remaining CDN URL anywhere in `src/`, it's a bug. Vendor it.

## 2. Django comment syntax (READ THIS BEFORE TOUCHING ANY TEMPLATE)

`{# ... #}` is **single-line only** in Django templates. The MOMENT you put
a newline inside, the parser stops treating it as a comment and renders the
WHOLE block as visible text in the browser. Multi-line comments REQUIRE
`{% comment %} ... {% endcomment %}`.

We have shipped this bug **THREE TIMES** so far:
- v1.0.29 -> v1.0.31 (command palette)
- v1.0.34 -> v1.0.35 (upload dropzone)
- v1.0.33 -> v1.0.38 (base.html alpine init)

Each one was caught by the user, not by a test. Before committing any
template change, run this check:

    grep -rn '{#[^#]*$' src/

If it returns ANYTHING, you have a multi-line `{# ... #}` and you need
to convert it to `{% comment %} ... {% endcomment %}` BEFORE committing.

## 3. Defensive coding for browser storage

Always wrap `localStorage` / `sessionStorage` access in `try/catch`. Edge's
"Tracking Prevention", Safari "Lockdown", Firefox "Strict", and private
windows can throw `SecurityError` on either read OR write. An unguarded
access inside `alpine:init` aborts the whole listener and breaks every
`$store.*` on the page (we hit this in v1.0.31).

`src/phoresis_ui/static/phoresis_ui/js/alpine-init.js` has reference helpers
(`safeLocalGet` / `safeLocalSet`) to copy the pattern from.

## 4. Git LFS for ML models

`src/gel_analyzer/static/gel_analyzer/ml/sam/{mobile_sam.pt,
mobilesam_decoder*.onnx}` and `src/gel_analyzer/static/gel_analyzer/ml/
gel_analysis.onnx` are tracked via Git LFS (see `.gitattributes`). A
`git clone` on a host without git-lfs installed returns ~134-byte
**pointer files** instead of the real ~40 MB binaries. The web container
boots fine (the SAM services are lazy-loaded) but the worker silently
fails the moment a band-detection task runs, deep inside onnxruntime
with a confusing "not a valid model" error.

`install.ps1` has a guard that detects pointer-sized SAM model files and
runs `git lfs install --local` + `git lfs pull` automatically (and
installs git-lfs via winget if missing). Don't remove that guard.

Manual recovery if git LFS wasn't on PATH at clone time:
    cd <repo>
    git lfs install --local
    git lfs pull

## 5. Settings: env-overridable in production

Anything that points at a writable filesystem path (STATIC_ROOT, MEDIA_ROOT,
log dirs, ML model dirs, ...) must be readable from `os.environ` with a
sensible local-dev fallback. Hardcoding `BASE_DIR / "X"` is a permission-denied
bomb the moment the container runs as a non-root user against a read-only
WORKDIR (we hit this in v1.0.18).

For ML model paths: anchor on `SRC_DIR` (`= BASE_DIR / "src"`), not
`BASE_DIR`, because source is COPY'd to `/app/src/...` in the Docker image.

## 6. Reverse proxy + Caddy

Production runs behind Caddy 2 at `https://phoresis`, with active health
probes against the upstream `web:8000`. That means:

- `ALLOWED_HOSTS` must include `web` (the Docker service name) on top of
  whatever public hosts the operator configured.
- `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` is
  required, otherwise `SESSION_COOKIE_SECURE=True` strips the cookie on
  every login response.
- `CSRF_TRUSTED_ORIGINS` must include the public origin(s); without it
  every POST returns 403.

## 7. Container init order

Web container entrypoint runs in this order, per spec §10.3:
`migrate -> collectstatic --clear --ignore "input.css" --ignore "tokens.css"
-> seed_groups -> seed_ladder_templates -> create_initial_users --from-env
--skip-existing -> exec gunicorn`. The `--ignore` flags are required because
WhiteNoise's manifest backend tries to post-process the Tailwind source CSS
otherwise. The `--skip-existing` for `create_initial_users` is intentional;
the same flag for `seed_ladder_templates` does NOT exist (the command is
already idempotent via `update_or_create`).

## 8. Login UX

Custom auth backend at `accounts.backends.EmailOrUsernameModelBackend`
accepts BOTH email and username (case-insensitive on email). install.ps1
asks the operator for an email; `create_initial_users` derives username
from the local part. Users naturally try logging in with the email they
entered, so the backend has to honour both.

## 9. Compose env-file resolution + media storage

`.env` lives at the project root (`<repo>/.env`) but the compose file is
at `docker/docker-compose.yml`. Compose v2 looks for `.env` next to the
compose file by default, NOT in the project root, so `${VAR}`
substitutions silently fall back to defaults when an operator runs
`docker compose` ad-hoc. **Solution**: `scripts/phoresis.ps1` always
passes `--env-file <root>/.env` and `-f docker/docker-compose.yml`.
Use it for ad-hoc ops; `install.ps1` / `update.ps1` do their own
plumbing via `_common.ps1`.

**Media storage** (v1.0.37): user-uploaded gel images, generated display
PNGs, thumbnails, and exports live in the Docker named volume
`phoresis_phoresis_media` -- NOT a host bind mount. Reason: Docker
Desktop's WSL2 file sharing on Windows produced silent divergence
between web (writes propagated to its own container) and caddy (reads
from a different host path), so caddy returned 404 for files Django
had successfully saved. With a Docker-managed volume, both containers
share the exact same storage with no host-filesystem layer.

**Volume protection** (v1.0.38): `phoresis_media` is declared as
`external: true` in compose.yml + `name: phoresis_phoresis_media`.
This means:

- `docker compose down -v` does NOT touch it -- compose treats
  external volumes as off-limits.
- `install.ps1` runs `docker volume create phoresis_phoresis_media`
  ahead of compose up. Idempotent: succeeds whether the volume
  already exists or not.
- The only supported way to wipe media is `scripts/wipe-media.ps1`,
  which (a) auto-backs up to `backups/auto/pre-wipe-<ts>.tar.gz`,
  (b) requires three separate confirmation prompts, (c) recreates an
  empty volume after the wipe so compose up still works.

If you ever NEED to wipe (e.g. test a fresh install): run
`wipe-media.ps1`, then `restore-media.ps1` to roll back if you change
your mind.

Backup / restore via dedicated scripts:
- `scripts/backup-media.ps1`  -- tarballs the volume to a Windows file
- `scripts/restore-media.ps1` -- reverses the above
- `scripts/backup.ps1`        -- DB + media combined snapshot (recommended for daily use)
- `scripts/restore.ps1`       -- pick from snapshots interactively
- `scripts/wipe-media.ps1`    -- nuclear, with safety net

## 10. PowerShell compatibility

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

## 11. Direct-to-main pushes

The user authorized direct pushes to `main` for the v1.0.x bug-hunt cycle
("fix directement dans le main hein"). For v1.1.x onward, prefer PRs unless
explicitly told otherwise.

## 12. macOS install (native, no Docker)

`scripts/mac/phoresis.sh` runs Phoresis on an Apple Silicon Mac as native processes under launchd
(`local.phoresis.{redis,web,worker,beat,caddy,mdns,nightly}`), next to other apps on the same Mac
(CamHub). Operator guide: `docs/INSTALL-MAC.md`. It does not replace or change the Windows / Docker
path. Rules learned while building it:

- **One site block, two ways to serve it.** `site_block` writes the Phoresis site once; it goes
  into Phoresis' own Caddyfile (`tls internal`) or, with `PHORESIS_SHARED_CADDY_DIR`, into a file
  read by the Caddy of the app that holds port 443 (`import shared_tls`). Never write a rule in one
  and not the other: the media check and the security headers live in that block.
- **Never bind or reuse another app's resources.** Ports are picked free at install and stored in
  `.env`; Redis is Phoresis' own instance (6390, password), never the Homebrew service on 6379;
  the database is a separate role + database in the shared PostgreSQL.
- **The script must run on the stock `/bin/bash` 3.2** (no associative arrays, no `mapfile`, no
  `${var,,}`), and every path may contain spaces (`~/Library/Application Support`, `/Volumes/My Disk`).
- **An automatic restart never migrates.** Only `install`, `restart` and `update` run
  migrate / collectstatic / seeds (same order as section 7).
- **Never create a folder on a disk that is not there.** A path under `/Volumes/<disk>` lands on the
  system disk when the disk is unplugged. The media archive requires its marker file and a mounted
  volume (`phoresis_core/media_tiers.py`); the backup checks the mount before `mkdir`.
- **External disks need Full Disk Access, for one program only**: the venv's real Python (a
  uv-managed interpreter, not Homebrew's). Keep it that way: Caddy never opens the archive disk
  (Django serves archived media), and the nightly job is started THROUGH that Python so bash, rsync
  and pg_dump run as its children. A launchd agent whose program is `/bin/bash` gets
  "Operation not permitted" on `/Volumes/<disk>`.
- **Use the `pg_dump` of the server's major version** (`pg_tool`): several PostgreSQL versions are
  installed side by side on the Mac, and the one on PATH may be older than the server.
- **Do not install the real services from a git worktree**, and do not load them on the user's
  behalf to try something: use `PHORESIS_LABEL_PREFIX`, `PHORESIS_ENV_FILE` (own ports, database and
  data folder) and `PHORESIS_ALLOW_WORKTREE=1` for a trial, then `uninstall`.
- **Media storage is `STORAGES["default"]`, always.** Code reads and writes media through the storage
  (`field.open()`, `storage.size()`), never through `MEDIA_ROOT` paths: with an archive disk a file
  may live outside `MEDIA_ROOT`.

## 13. Sign-in security

Lockout after failed logins (django-axes), two-factor (django-otp) and password rules; the details
are in `src/accounts/docs/README.md`. Rules to keep:

- **No way in that skips the session.** The second factor lives in the session and is enforced by
  `accounts.middleware.TwoFactorMiddleware`. DRF therefore accepts `SessionAuthentication` only:
  adding Basic or token authentication opens a password-only (or code-less) door to the whole API.
- **`/media/` stays behind `forward_auth`** in both Caddy configurations (`docker/Caddyfile`,
  `site_block` in `scripts/mac/phoresis.sh`), pointing at `/api/auth/media/`. Caddy serves the
  files itself: without that line a gel image is readable by whoever has its URL, signed in or not.
- **`axes.backends.AxesStandaloneBackend` stays first** in `AUTHENTICATION_BACKENDS` and
  `axes.middleware.AxesMiddleware` last in `MIDDLEWARE`.
- **Never lock out per address alone.** Behind Docker Desktop all browsers share the gateway's
  address; `AXES_LOCKOUT_PARAMETERS` is the (account, address) pair.
- **The setup page is closed to an enrolled, unverified session**: otherwise a stolen password could
  add its own authenticator.
- `PHORESIS_REQUIRE_2FA` defaults to `off` so that an update never surprises an existing Windows
  install; the Mac installer writes `staff`.
