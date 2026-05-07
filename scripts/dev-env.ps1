# Dot-source this file from a PowerShell session to export the env vars that
# `manage.py runserver` (running on Windows) needs to connect to the Docker
# devstack (Postgres on host:15432, Redis on host:16379) and to share media
# files with the worker container.
#
# Usage (note the leading dot + space — that's PowerShell's "dot-source"):
#
#     . .\scripts\dev-env.ps1
#     .venv\Scripts\python.exe manage.py runserver
#
# After dot-sourcing, the env vars persist for the LIFETIME OF THIS SHELL.
# Open a fresh terminal and you'll need to dot-source again.
#
# Why dot-source instead of `& .\dev-env.ps1`?  When you call a script with `&`,
# PowerShell runs it in a child scope and the env vars vanish when it exits.
# Dot-sourcing executes it in the current scope so the vars stick.

$Script:RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path

$env:DJANGO_SETTINGS_MODULE = 'phoresis.settings.dev'
$env:DJANGO_DEBUG           = 'true'

# DB / Redis are exported under the PHORESIS_* namespace because
# `phoresis.settings.dev` (on bare metal) ignores generic `DB_*` /
# `REDIS_*` env vars to avoid being hijacked by sibling-project vars
# (e.g. an Azure Postgres set at OS user level). The PHORESIS_* names
# are the documented escape hatch. Inside Docker, the compose stack
# injects `DB_*` / `REDIS_*` directly and dev.py honours those.

# DB → dev postgres in docker (host port 15432, internal 5432 via 127.0.0.1)
$env:PHORESIS_DB_HOST     = '127.0.0.1'
$env:PHORESIS_DB_PORT     = '15432'
$env:PHORESIS_DB_NAME     = 'phoresis'
$env:PHORESIS_DB_USER     = 'phoresis'
$env:PHORESIS_DB_PASSWORD = 'phoresis'

# Redis → dev redis in docker (host port 16379)
$env:PHORESIS_REDIS_HOST  = '127.0.0.1'
$env:PHORESIS_REDIS_PORT  = '16379'

# Media path — same host folder that the worker container bind-mounts at
# /srv/media. Default keeps it co-located with the repo (gitignored).
$defaultMedia = Join-Path $Script:RepoRoot '_dev_media'
if (-not (Test-Path $defaultMedia)) {
    New-Item -ItemType Directory -Path $defaultMedia -Force | Out-Null
}
$env:MEDIA_ROOT = $defaultMedia

# Note: DJANGO_ALLOWED_HOSTS is NOT exported here because phoresis.settings.dev
# hardcodes ALLOWED_HOSTS = ["localhost", "127.0.0.1", "phoresis"] after
# `from .base import *`, so any env-var override would be silently dropped.
# Setting it would only mislead future contributors into thinking they could
# tweak ALLOWED_HOSTS via env in dev — they can't.

Write-Host ""
Write-Host "Phoresis dev env loaded:" -ForegroundColor Green
Write-Host "  DB     : $($env:PHORESIS_DB_USER)@$($env:PHORESIS_DB_HOST):$($env:PHORESIS_DB_PORT)/$($env:PHORESIS_DB_NAME)"
Write-Host "  Redis  : $($env:PHORESIS_REDIS_HOST):$($env:PHORESIS_REDIS_PORT)"
Write-Host "  Media  : $($env:MEDIA_ROOT)"
Write-Host "  Django : $($env:DJANGO_SETTINGS_MODULE) (DEBUG=$($env:DJANGO_DEBUG))"
Write-Host ""
Write-Host "Now run:" -ForegroundColor Cyan
Write-Host "  .venv\Scripts\python.exe manage.py migrate"
Write-Host "  .venv\Scripts\python.exe manage.py runserver"
Write-Host ""
