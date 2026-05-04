<#
.SYNOPSIS
    Thin wrapper around `docker compose` for the Phoresis stack.

.DESCRIPTION
    Always passes `--env-file <project root>/.env` and `-f docker/docker-compose.yml`
    so all the ${VAR} substitutions in compose.yml (PHORESIS_MEDIA_DIR,
    PHORESIS_IMAGE_VARIANT, ...) resolve correctly. Without this, compose
    looks for `.env` next to the compose file (in `docker/`), doesn't find
    it, and silently falls back to wrong defaults -- which has bitten us
    once already (Caddy mounted at the wrong host path so /media/ 404'd
    even though Django wrote files correctly).

.EXAMPLE
    .\scripts\phoresis.ps1 ps
    .\scripts\phoresis.ps1 logs web --tail 50
    .\scripts\phoresis.ps1 exec web python manage.py shell
    .\scripts\phoresis.ps1 up -d --force-recreate caddy

.NOTES
    For first-time install / update / rollback, use the dedicated scripts
    (install.ps1, update.ps1) instead -- those do extra setup work beyond
    just `docker compose`.
#>
[CmdletBinding(PositionalBinding=$false)]
param(
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$ComposeArgs
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root '.env'
$composeFile = Join-Path $root 'docker\docker-compose.yml'

if (-not (Test-Path $envFile)) {
    Write-Host "[ERROR] .env not found at $envFile" -ForegroundColor Red
    Write-Host "        Run scripts\install.ps1 first." -ForegroundColor Red
    exit 1
}

# Detect GPU variant -> include compose.gpu.yml if present.
$variant = (Get-Content $envFile | Select-String -Pattern '^PHORESIS_IMAGE_VARIANT=' | ForEach-Object {
    ($_ -split '=', 2)[1].Trim()
}) | Select-Object -First 1
$gpuFile = Join-Path $root 'docker\compose.gpu.yml'
$gpuArgs = @()
if ($variant -eq 'cuda' -and (Test-Path $gpuFile)) {
    $gpuArgs = @('-f', $gpuFile)
}

& docker compose -f $composeFile @gpuArgs --env-file $envFile @ComposeArgs
exit $LASTEXITCODE
