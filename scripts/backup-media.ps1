<#
.SYNOPSIS
    Backup the Phoresis media volume (uploaded gels, display PNGs, thumbnails)
    to a single .tar.gz file.

.DESCRIPTION
    Phoresis stores all user-uploaded media in a Docker-managed named volume
    `phoresis_phoresis_media`. To back it up to a regular Windows file (so
    you can copy it to OneDrive / NAS / external disk), this script spins
    up a throwaway alpine container, mounts the volume, and tars it to the
    destination path.

.PARAMETER Destination
    Path to the .tar.gz file to create. Defaults to
    `<repo>/backups/phoresis-media-<timestamp>.tar.gz`.

.EXAMPLE
    .\scripts\backup-media.ps1
    .\scripts\backup-media.ps1 -Destination D:\Backups\phoresis-media.tar.gz
#>
[CmdletBinding()]
param(
    [string]$Destination
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

if (-not $Destination) {
    $stamp = (Get-Date).ToString('yyyy-MM-dd_HHmmss')
    $backupsDir = Join-Path $root 'backups'
    if (-not (Test-Path $backupsDir)) { New-Item -ItemType Directory -Path $backupsDir -Force | Out-Null }
    $Destination = Join-Path $backupsDir "phoresis-media-$stamp.tar.gz"
}

$destAbs = [System.IO.Path]::GetFullPath($Destination)
$destDir = Split-Path -Parent $destAbs
$destFile = Split-Path -Leaf $destAbs

if (-not (Test-Path $destDir)) {
    New-Item -ItemType Directory -Path $destDir -Force | Out-Null
}

# Convert Windows path to forward-slash for Docker.
$destDirForward = $destDir -replace '\\', '/'

Write-Host "Backing up phoresis_phoresis_media -> $destAbs ..."
& docker run --rm `
    -v phoresis_phoresis_media:/data:ro `
    -v "${destDirForward}:/backup" `
    alpine:3 `
    sh -c "cd /data && tar czf /backup/$destFile ."

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Backup failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

$size = (Get-Item $destAbs).Length
$sizeMB = [math]::Round($size / 1MB, 1)
Write-Host "[OK] Backup written: $destAbs ($sizeMB MB)" -ForegroundColor Green
