<#
.SYNOPSIS
    Back up the Phoresis database + media files.

.DESCRIPTION
    Writes to %USERPROFILE%\Phoresis-Backups\YYYY-MM-DD_HHmmss\.
    Keeps 30 days of backups; older snapshots are pruned automatically.

.PARAMETER OutDir
    Override the default backup directory.

.EXAMPLE
    .\scripts\backup.ps1

.EXAMPLE
    .\scripts\backup.ps1 -OutDir "D:\Phoresis-Backups"
#>
[CmdletBinding()]
param(
    [string]$OutDir = (Join-Path $env:USERPROFILE 'Phoresis-Backups'),
    [int]$RetentionDays = 30
)

. "$PSScriptRoot\_common.ps1"

if (-not (Test-Path $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir | Out-Null
}

$timestamp = (Get-Date -Format 'yyyy-MM-dd_HHmmss')
$snapshotDir = Join-Path $OutDir $timestamp
New-Item -ItemType Directory -Path $snapshotDir | Out-Null

Write-Step "Backing up to $snapshotDir"

# --- 1. pg_dump (compressed) ---
$envMap = Read-EnvFile (Join-Path $Script:RepoRoot '.env')
$dbName = $envMap['DB_NAME']; if (-not $dbName) { $dbName = 'phoresis' }
$dbUser = $envMap['DB_USER']; if (-not $dbUser) { $dbUser = 'phoresis' }
$dbPwd  = $envMap['DB_PASSWORD']; if (-not $dbPwd) { $dbPwd = 'phoresis' }
$dbHost = '127.0.0.1'  # always native on the host, never via host.docker.internal here
$dbPort = $envMap['DB_PORT']; if (-not $dbPort) { $dbPort = '5432' }

Write-Sub "pg_dump $dbName"
$dbDump = Join-Path $snapshotDir 'db.sql.gz'
$env:PGPASSWORD = $dbPwd
try {
    & pg_dump -U $dbUser -h $dbHost -p $dbPort -F p $dbName | & gzip -c > $dbDump
    if ($LASTEXITCODE -ne 0) { throw "pg_dump exit $LASTEXITCODE" }
    Write-Ok "DB dump: $((Get-Item $dbDump).Length / 1MB | ForEach-Object { '{0:F2} MB' -f $_ })"
} finally {
    $env:PGPASSWORD = $null
}

# --- 2. Media volume tar ---
Write-Sub "tar phoresis_media"
$mediaTar = Join-Path $snapshotDir 'media.tar.gz'

# Run a tar inside an alpine container with the volume mounted
& docker run --rm `
    -v phoresis_phoresis_media:/data:ro `
    -v "$($snapshotDir):/backup" `
    alpine:3 sh -c "cd /data && tar czf /backup/media.tar.gz ."
if ($LASTEXITCODE -ne 0) {
    Write-Warn "media tar failed (exit $LASTEXITCODE) - DB backup is preserved"
} else {
    Write-Ok "Media tar: $((Get-Item $mediaTar).Length / 1MB | ForEach-Object { '{0:F2} MB' -f $_ })"
}

# --- 3. Metadata ---
$meta = @{
    timestamp        = $timestamp
    db_size_bytes    = (Get-Item $dbDump).Length
    media_size_bytes = if (Test-Path $mediaTar) { (Get-Item $mediaTar).Length } else { 0 }
    image_variant    = $envMap['PHORESIS_IMAGE_VARIANT']
    image_tag_pin    = $envMap['PHORESIS_IMAGE_TAG']
}
$meta | ConvertTo-Json | Set-Content -Path (Join-Path $snapshotDir 'meta.json') -Encoding UTF8
Write-Ok "meta.json written"

# --- 4. Retention ---
Write-Step "Pruning backups older than $RetentionDays days"
$cutoff = (Get-Date).AddDays(-$RetentionDays)
Get-ChildItem -Path $OutDir -Directory | Where-Object {
    $_.CreationTime -lt $cutoff -and $_.Name -match '^\d{4}-\d{2}-\d{2}_\d{6}$'
} | ForEach-Object {
    Write-Sub "Removing $($_.Name)"
    Remove-Item -Path $_.FullName -Recurse -Force
}

Write-Host ""
Write-Host "  Backup complete: $snapshotDir" -ForegroundColor Green
