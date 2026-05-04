<#
.SYNOPSIS
    Permanently wipe the Phoresis media volume.

.DESCRIPTION
    DESTRUCTIVE. Removes ALL uploaded gel images, generated display PNGs,
    thumbnails, and exports stored in the Docker named volume
    `phoresis_phoresis_media`.

    Safety mechanisms:
    1. Auto-backup to backups\auto\pre-wipe-<timestamp>.tar.gz before wipe.
    2. Triple confirmation -- you must type three different phrases.
    3. The Docker volume is `external: true` in compose.yml, so it
       SHOULD be impossible to wipe accidentally via `compose down -v`.
       This script is the supported path.

    The auto-backup tarball is kept in backups\auto\ -- if you ever
    need to recover, see scripts\restore-media.ps1.

.PARAMETER SkipBackup
    Don't create the auto-backup. Only useful if you're about to redo
    the wipe right after another one (rare). Default: false.

.PARAMETER YesIMeanIt
    Skip the triple-confirmation prompt. Default: false. Use only in
    automated scripts where you've already confirmed the intent.

.EXAMPLE
    .\scripts\wipe-media.ps1
    .\scripts\wipe-media.ps1 -YesIMeanIt
#>
[CmdletBinding()]
param(
    [switch]$SkipBackup,
    [switch]$YesIMeanIt
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

# 1. Sanity check -- volume must exist.
$exists = (& docker volume ls -q --filter "name=^phoresis_phoresis_media$" | Out-String).Trim()
if (-not $exists) {
    Write-Host "[INFO] phoresis_phoresis_media doesn't exist -- nothing to wipe." -ForegroundColor Yellow
    exit 0
}

# 2. Triple confirmation.
if (-not $YesIMeanIt) {
    Write-Host ""
    Write-Host "  WARNING: this will PERMANENTLY DELETE all media in" -ForegroundColor Red
    Write-Host "           the Phoresis stack (uploaded gels, displays, thumbnails)." -ForegroundColor Red
    Write-Host ""

    $r1 = Read-Host "  Step 1/3 -- type 'wipe' to continue"
    if ($r1 -ne 'wipe') { Write-Host "Aborted."; exit 0 }

    $r2 = Read-Host "  Step 2/3 -- type the volume name 'phoresis_phoresis_media' to confirm"
    if ($r2 -ne 'phoresis_phoresis_media') { Write-Host "Aborted."; exit 0 }

    $r3 = Read-Host "  Step 3/3 -- type 'I have a backup' (literally) or press Enter to abort"
    if ($r3 -ne 'I have a backup') { Write-Host "Aborted."; exit 0 }
}

# 3. Auto-backup unless explicitly skipped.
if (-not $SkipBackup) {
    Write-Host ""
    Write-Host "==> Creating safety backup before wipe..."
    $autoDir = Join-Path $root 'backups\auto'
    if (-not (Test-Path $autoDir)) { New-Item -ItemType Directory -Path $autoDir -Force | Out-Null }
    $stamp = (Get-Date).ToString('yyyy-MM-dd_HHmmss')
    $autoPath = Join-Path $autoDir "pre-wipe-$stamp.tar.gz"
    & (Join-Path $PSScriptRoot 'backup-media.ps1') -Destination $autoPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Pre-wipe backup failed -- ABORTING wipe to protect your data." -ForegroundColor Red
        Write-Host "        Re-run with -SkipBackup if you really want to wipe anyway." -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] Safety backup at $autoPath" -ForegroundColor Green
}

# 4. Stop containers that hold the volume open, then remove it.
$composeFile = Join-Path $root 'docker\docker-compose.yml'
$envFile = Join-Path $root '.env'
$composeArgs = @('-f', $composeFile)
if (Test-Path $envFile) { $composeArgs += @('--env-file', $envFile) }

Write-Host ""
Write-Host "==> Stopping containers that mount the volume..."
& docker compose @composeArgs stop web worker scheduler caddy 2>$null

Write-Host "==> Removing volume phoresis_phoresis_media..."
& docker volume rm phoresis_phoresis_media
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] docker volume rm failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "==> Recreating empty volume so a subsequent compose up works..."
& docker volume create phoresis_phoresis_media | Out-Null

Write-Host ""
Write-Host "[OK] Media wiped. Restart the stack with: .\scripts\phoresis.ps1 up -d" -ForegroundColor Green
if (-not $SkipBackup) {
    Write-Host "     If you change your mind: .\scripts\restore-media.ps1 -Source $autoPath" -ForegroundColor Green
}
