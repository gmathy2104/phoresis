<#
.SYNOPSIS
    Restore Phoresis from a backup snapshot - interactive selection.

.DESCRIPTION
    Lists available snapshots, prompts which to restore, restores DB + media.
    The Phoresis stack should be DOWN before restoring (script checks).

.PARAMETER InDir
    Backup directory (default: %USERPROFILE%\Phoresis-Backups).

.PARAMETER Snapshot
    Skip the interactive prompt by passing a snapshot directory name (e.g. 2026-05-03_143000).
#>
[CmdletBinding()]
param(
    [string]$InDir = (Join-Path $env:USERPROFILE 'Phoresis-Backups'),
    [string]$Snapshot
)

. "$PSScriptRoot\_common.ps1"

if (-not (Test-Path $InDir)) {
    Write-Err "Backup directory not found: $InDir"
    exit 1
}

$snapshots = Get-ChildItem -Path $InDir -Directory |
    Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}_\d{6}$' } |
    Sort-Object CreationTime -Descending

if (-not $snapshots) {
    Write-Err "No backups found in $InDir"
    exit 1
}

# --- 1. Pick a snapshot ---
if ($Snapshot) {
    $picked = $snapshots | Where-Object Name -EQ $Snapshot
    if (-not $picked) { Write-Err "Snapshot not found: $Snapshot"; exit 1 }
} else {
    Write-Step "Available snapshots"
    for ($i = 0; $i -lt $snapshots.Count; $i++) {
        $s = $snapshots[$i]
        $size = (Get-ChildItem -Recurse -File -Path $s.FullName | Measure-Object Length -Sum).Sum
        Write-Host ("    [{0}] {1}    {2:F1} MB    {3}" -f ($i+1), $s.Name, ($size/1MB), $s.CreationTime)
    }
    $choice = Read-Host "`nWhich snapshot? (number or empty to abort)"
    if (-not $choice) { Write-Err "Aborted."; exit 1 }
    $idx = [int]$choice - 1
    if ($idx -lt 0 -or $idx -ge $snapshots.Count) { Write-Err "Out of range."; exit 1 }
    $picked = $snapshots[$idx]
}

Write-Step "Restoring $($picked.Name)"

# --- 2. Stack must be DOWN ---
$composeArgs = Get-ComposeArgs
$running = (& docker compose @composeArgs ps -q).Trim()
if ($running) {
    Write-Warn "The Phoresis stack is still running. Stopping it first..."
    & docker compose @composeArgs down
}

# --- 3. Confirm ---
Write-Warn "This will OVERWRITE the current Phoresis database and media files."
$confirm = Read-Host "Type 'RESTORE' to confirm"
if ($confirm -ne 'RESTORE') { Write-Err "Aborted."; exit 1 }

# --- 4. DB restore ---
$envMap = Read-EnvFile (Join-Path $Script:RepoRoot '.env')
$dbName = $envMap['DB_NAME']; if (-not $dbName) { $dbName = 'phoresis' }
$dbUser = $envMap['DB_USER']; if (-not $dbUser) { $dbUser = 'phoresis' }
$dbPwd  = $envMap['DB_PASSWORD']; if (-not $dbPwd) { $dbPwd = 'phoresis' }
$dbHost = '127.0.0.1'
$dbPort = $envMap['DB_PORT']; if (-not $dbPort) { $dbPort = '5432' }

Write-Sub "Recreating database"
$env:PGPASSWORD = $dbPwd
try {
    & psql -U postgres -h $dbHost -p $dbPort -d postgres -c "DROP DATABASE IF EXISTS $dbName WITH (FORCE);"
    & psql -U postgres -h $dbHost -p $dbPort -d postgres -c "CREATE DATABASE $dbName OWNER $dbUser;"

    Write-Sub "Restoring db.sql.gz"
    $dbDump = Join-Path $picked.FullName 'db.sql.gz'
    & gzip -dc $dbDump | & psql -U $dbUser -h $dbHost -p $dbPort -d $dbName
    if ($LASTEXITCODE -ne 0) { throw "psql restore exit $LASTEXITCODE" }
    Write-Ok "DB restored"
} finally {
    $env:PGPASSWORD = $null
}

# --- 5. Media restore ---
$mediaTar = Join-Path $picked.FullName 'media.tar.gz'
if (Test-Path $mediaTar) {
    Write-Sub "Restoring media.tar.gz"
    $mediaDst = Get-MediaDir
    if (-not (Test-Path $mediaDst)) {
        New-Item -ItemType Directory -Path $mediaDst -Force | Out-Null
    }
    $mediaDstForward = $mediaDst -replace '\\', '/'
    $pickedForward   = $picked.FullName -replace '\\', '/'
    & docker run --rm `
        -v "${mediaDstForward}:/data" `
        -v "${pickedForward}:/backup:ro" `
        alpine:3 sh -c "cd /data && rm -rf ./* && tar xzf /backup/media.tar.gz"
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "media restore failed (exit $LASTEXITCODE) - DB is restored"
    } else {
        Write-Ok "Media restored"
    }
}

Write-Step "Bringing the stack back up"
& docker compose @composeArgs up -d

if (Wait-HttpOk -Url 'https://phoresis/healthz/live/' -TimeoutSeconds 90) {
    Write-Ok "Restore complete. https://phoresis/ is back up."
} else {
    Write-Err "Healthcheck timed out post-restore. Investigate via docker compose logs."
    exit 1
}
