<#
.SYNOPSIS
    Stop the Phoresis stack. Volumes are preserved.

.DESCRIPTION
    `docker compose down` only - does NOT pass -v, so phoresis_staticfiles,
    phoresis_media, phoresis_redis, caddy_data, caddy_config all survive.
    To wipe everything (DEV ONLY), pass -Wipe.
#>
[CmdletBinding()]
param(
    [switch]$Wipe
)

. "$PSScriptRoot\_common.ps1"

$envMap = Read-EnvFile (Join-Path $Script:RepoRoot '.env')
$variant = $envMap['PHORESIS_IMAGE_VARIANT']
if (-not $variant) { $variant = 'cpu' }

$composeArgs = Get-ComposeArgs -WithGpu:($variant -eq 'cuda')

if ($Wipe) {
    Write-Warn "WIPE MODE - this will delete static, media, redis, and caddy volumes."
    Write-Warn "Postgres data on the HOST is unaffected (always)."
    $confirm = Read-Host "Type 'WIPE' to confirm"
    if ($confirm -ne 'WIPE') {
        Write-Err "Aborted."
        exit 1
    }
    Write-Step "docker compose down -v"
    & docker compose @composeArgs down -v
} else {
    Write-Step "docker compose down (volumes preserved)"
    & docker compose @composeArgs down
}

if ($LASTEXITCODE -eq 0) {
    Write-Ok "Phoresis stopped."
} else {
    Write-Err "docker compose down failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}
