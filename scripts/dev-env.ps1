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

# DB → dev postgres in docker (host port 15432, internal 5432 via 127.0.0.1)
$env:DB_HOST     = '127.0.0.1'
$env:DB_PORT     = '15432'
$env:DB_NAME     = 'phoresis'
$env:DB_USER     = 'phoresis'
$env:DB_PASSWORD = 'phoresis'

# Redis → dev redis in docker (host port 16379)
$env:REDIS_HOST  = '127.0.0.1'
$env:REDIS_PORT  = '16379'

# Media path — same host folder that the worker container bind-mounts at
# /srv/media. Default keeps it co-located with the repo (gitignored).
$defaultMedia = Join-Path $Script:RepoRoot '_dev_media'
if (-not (Test-Path $defaultMedia)) {
    New-Item -ItemType Directory -Path $defaultMedia -Force | Out-Null
}
$env:MEDIA_ROOT = $defaultMedia

# Mute Django debug-toolbar internal IP check noise on a non-INTERNAL_IPS box.
$env:DJANGO_ALLOWED_HOSTS = 'localhost,127.0.0.1'

Write-Host ""
Write-Host "Phoresis dev env loaded:" -ForegroundColor Green
Write-Host "  DB     : $($env:DB_USER)@$($env:DB_HOST):$($env:DB_PORT)/$($env:DB_NAME)"
Write-Host "  Redis  : $($env:REDIS_HOST):$($env:REDIS_PORT)"
Write-Host "  Media  : $($env:MEDIA_ROOT)"
Write-Host "  Django : $($env:DJANGO_SETTINGS_MODULE) (DEBUG=$($env:DJANGO_DEBUG))"
Write-Host ""
Write-Host "Now run:" -ForegroundColor Cyan
Write-Host "  .venv\Scripts\python.exe manage.py migrate"
Write-Host "  .venv\Scripts\python.exe manage.py runserver"
Write-Host ""
