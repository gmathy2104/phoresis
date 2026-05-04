<#
.SYNOPSIS
    Restore the Phoresis media volume from a backup tarball produced by
    backup-media.ps1.

.DESCRIPTION
    DESTRUCTIVE: wipes the existing `phoresis_phoresis_media` volume contents
    before restoring. Stop the stack first (`.\scripts\phoresis.ps1 stop`)
    or confirm with -Force.

.PARAMETER Source
    Path to the .tar.gz backup file.

.PARAMETER Force
    Skip the confirmation prompt.

.EXAMPLE
    .\scripts\restore-media.ps1 -Source D:\Backups\phoresis-media.tar.gz
    .\scripts\restore-media.ps1 -Source backups\phoresis-media-2026-05-04_123045.tar.gz -Force
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Source,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$srcAbs = [System.IO.Path]::GetFullPath($Source)
if (-not (Test-Path $srcAbs)) {
    Write-Host "[ERROR] Backup file not found: $srcAbs" -ForegroundColor Red
    exit 1
}

if (-not $Force) {
    Write-Host "This will WIPE all current media in phoresis_phoresis_media and replace with $srcAbs"
    $reply = Read-Host "Continue? (yes/no)"
    if ($reply -ne 'yes') {
        Write-Host "Aborted."
        exit 0
    }
}

$srcDir = Split-Path -Parent $srcAbs
$srcFile = Split-Path -Leaf $srcAbs
$srcDirForward = $srcDir -replace '\\', '/'

Write-Host "Restoring $srcAbs -> phoresis_phoresis_media ..."
& docker run --rm `
    -v phoresis_phoresis_media:/data `
    -v "${srcDirForward}:/backup:ro" `
    alpine:3 `
    sh -c "rm -rf /data/* /data/.[!.]* 2>/dev/null; tar xzf /backup/$srcFile -C /data"

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Restore failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "[OK] Restore complete." -ForegroundColor Green
Write-Host "     Restart the stack so the containers pick up the restored files:"
Write-Host "         .\scripts\phoresis.ps1 restart"
