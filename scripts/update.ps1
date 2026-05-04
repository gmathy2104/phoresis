<#
.SYNOPSIS
    Update Phoresis to the newest tagged release (or roll back to a specific tag).

.PARAMETER Rollback
    Pin the stack to a specific version tag (e.g. v0.4.0). Disables Watchtower
    auto-update by writing PHORESIS_IMAGE_TAG to .env, which the compose file
    consults via ${PHORESIS_IMAGE_TAG:-latest-${variant}}.

.EXAMPLE
    .\scripts\update.ps1                    # pull latest, restart

.EXAMPLE
    .\scripts\update.ps1 -Rollback v0.4.0   # pin to v0.4.0
#>
[CmdletBinding()]
param(
    [string]$Rollback
)

. "$PSScriptRoot\_common.ps1"

$envPath = Join-Path $Script:RepoRoot '.env'
$envMap  = Read-EnvFile $envPath
$variant = $envMap['PHORESIS_IMAGE_VARIANT']
if (-not $variant) { $variant = 'cpu' }

if ($Rollback) {
    if ($Rollback -notmatch '^v\d+\.\d+\.\d+$') {
        Write-Err "Rollback tag must look like 'v1.2.3'."
        exit 1
    }
    Write-Step "Pinning to $Rollback-$variant"
    $envMap['PHORESIS_IMAGE_TAG']    = $Rollback
    $envMap['PHORESIS_WEB_IMAGE']    = "ghcr.io/gmathy2104/phoresis-web:$Rollback-$variant"
    $envMap['PHORESIS_WORKER_IMAGE'] = "ghcr.io/gmathy2104/phoresis-worker:$Rollback-$variant"
    Write-EnvFile -Path $envPath -Map $envMap
    Write-Ok ".env updated"
} else {
    # Clear any pin set by a previous rollback
    if ($envMap.ContainsKey('PHORESIS_IMAGE_TAG')) {
        Write-Sub "Clearing previous version pin"
        $envMap.Remove('PHORESIS_IMAGE_TAG') | Out-Null
        $envMap.Remove('PHORESIS_WEB_IMAGE') | Out-Null
        $envMap.Remove('PHORESIS_WORKER_IMAGE') | Out-Null
        Write-EnvFile -Path $envPath -Map $envMap
    }
}

$composeArgs = Get-ComposeArgs -WithGpu:($variant -eq 'cuda')

# CPU images are pulled from ghcr.io. CUDA images are built locally
# (GPU machines build their own — see install.ps1 step 6 + docs/INSTALL.md).
if ($variant -eq 'cuda') {
    Write-Step "docker compose build (cuda — local rebuild)"
    & docker compose @composeArgs build --build-arg TORCH_VARIANT=cuda
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Build failed (exit $LASTEXITCODE)"
        exit $LASTEXITCODE
    }
} else {
    Write-Step "docker compose pull"
    & docker compose @composeArgs pull
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Pull failed (exit $LASTEXITCODE)"
        exit $LASTEXITCODE
    }
}

Write-Step "docker compose up -d (rolling restart)"
& docker compose @composeArgs up -d
if ($LASTEXITCODE -ne 0) {
    Write-Err "Up failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

Write-Step "Waiting for healthcheck"
if (Wait-HttpOk -Url 'https://phoresis/healthz/live/' -TimeoutSeconds 90) {
    if ($Rollback) {
        Write-Ok "Rolled back to $Rollback. Watchtower auto-update is paused while a tag is pinned."
        Write-Sub "To resume auto-updates, re-run: .\scripts\update.ps1"
    } else {
        Write-Ok "Phoresis updated to latest."
    }
} else {
    Write-Err "Post-update healthcheck failed. Run: docker compose $($composeArgs -join ' ') logs"
    exit 1
}
