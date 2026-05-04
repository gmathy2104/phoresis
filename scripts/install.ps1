<#
.SYNOPSIS
    Phoresis clean-machine installer (Windows 11).

.DESCRIPTION
    Idempotent: re-runs cleanly on partially-installed machines.
    Installs Docker Desktop + PostgreSQL 17 if missing, configures the
    Phoresis stack, generates .env interactively, and brings up
    https://phoresis/.

.PARAMETER Variant
    Force CPU or CUDA image variant. Default: auto-detect.

.PARAMETER SkipBrowserOpen
    Don't open https://phoresis/ at the end.

.EXAMPLE
    Right-click > Run with PowerShell (as Admin)

.EXAMPLE
    .\scripts\install.ps1 -Variant cpu
#>
[CmdletBinding()]
param(
    [ValidateSet('auto', 'cpu', 'cuda')]
    [string]$Variant = 'auto',

    [switch]$SkipBrowserOpen
,
    [string]$DataDir = (Join-Path $env:USERPROFILE 'Phoresis-Data')
)

. "$PSScriptRoot\_common.ps1"

# Convert a SecureString to plaintext in a way that works on PowerShell 5.1+.
function ConvertFrom-SecureToPlain {
    param([Parameter(Mandatory)][System.Security.SecureString]$Secure)
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

Write-Host @"

  ____  _                          _
 |  _ \| |__   ___  _ __ ___  ___ (_)___
 | |_) | '_ \ / _ \| '__/ _ \/ __|| / __|
 |  __/| | | | (_) | | |  __/\__ \| \__ \
 |_|   |_| |_|\___/|_|  \___||___/|_|___/

  Standalone gel analyzer - installer

"@ -ForegroundColor Blue

# --- 0. Pre-flight ---
Assert-Admin

Write-Step "Verifying Windows 10/11"
$os = Get-CimInstance Win32_OperatingSystem
if (-not ($os.Caption -match "Windows 1[01]")) {
    Write-Err "Phoresis requires Windows 10 or 11 (detected: $($os.Caption))"
    exit 1
}
Write-Ok "$($os.Caption)"

# --- 1. Docker Desktop ---
Write-Step "Docker Desktop"
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Write-Sub "Installing Docker Desktop via winget..."
    winget install --silent --accept-package-agreements --accept-source-agreements Docker.DockerDesktop
    Write-Warn "Docker Desktop installed. You may need to sign out and back in for WSL2 integration to settle."
    Write-Warn "Re-run this script after that. Exiting now."
    exit 0
}
Write-Ok "docker CLI present ($(docker --version))"

# Ensure daemon is reachable
$dockerOk = $false
for ($i = 0; $i -lt 30; $i++) {
    try { docker info --format '{{.ServerVersion}}' | Out-Null; $dockerOk = $true; break }
    catch { Start-Sleep -Seconds 2 }
}
if (-not $dockerOk) {
    Write-Err "Docker daemon not responding. Start Docker Desktop manually and re-run."
    exit 1
}
Write-Ok "Docker daemon reachable"

# --- 2. PostgreSQL 17 ---
Write-Step "PostgreSQL 17"
$psql = Get-Command psql -ErrorAction SilentlyContinue
if (-not $psql) {
    Write-Sub "Installing PostgreSQL 17 via winget..."
    winget install --silent --accept-package-agreements --accept-source-agreements PostgreSQL.PostgreSQL.17
    Write-Warn "Postgres installed. Set the 'postgres' user password during install if prompted."
    Write-Warn "Re-run this script after Postgres is configured."
    exit 0
}
Write-Ok "psql present ($(psql --version))"

# Create phoresis DB + user (idempotent)
Write-Sub "Provisioning 'phoresis' database + user"
$pgPassword = Read-Host "Postgres superuser ('postgres') password" -AsSecureString
$pgPasswordPlain = ConvertFrom-SecureToPlain -Secure $pgPassword

$env:PGPASSWORD = $pgPasswordPlain
$initSql = @"
DO `$`$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'phoresis') THEN
      CREATE ROLE phoresis WITH LOGIN PASSWORD 'phoresis' SUPERUSER;
   END IF;
END
`$`$;
SELECT 'created' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'phoresis')
\gexec
CREATE DATABASE phoresis OWNER phoresis;
"@
$initSql | psql -U postgres -h 127.0.0.1 -d postgres
$env:PGPASSWORD = $null
Write-Ok "phoresis DB + user ready"

# --- 3. GPU detection ---
# The CUDA image ships PyTorch built with cu128 (CUDA 12.8), which officially
# supports compute capability sm_70+ (Volta and newer). Older GPUs (Pascal
# sm_61, Maxwell sm_50/52) silently fall back to CPU at runtime even with
# the CUDA image, so we explicitly route them to the CPU variant here.
Write-Step "GPU variant"
$resolvedVariant = $Variant
if ($Variant -eq 'auto') {
    $nvSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($nvSmi) {
        try {
            $gpus = & nvidia-smi --query-gpu=name --format=csv,noheader 2>$null
            $caps = & nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>$null
            if ($LASTEXITCODE -eq 0 -and $gpus) {
                $minCap = ($caps | ForEach-Object { [decimal]$_.Trim() } | Measure-Object -Minimum).Minimum
                if ($minCap -ge 7.5) {
                    Write-Ok "NVIDIA GPU detected: $gpus (compute capability $minCap >= 7.5)"
                    $resolvedVariant = 'cuda'
                } else {
                    Write-Warn "GPU compute capability $minCap is below 7.5 (Volta/Turing+)."
                    Write-Warn "PyTorch cu128 wheels do not officially support pre-Volta cards;"
                    Write-Warn "falling back to CPU image. Override with -Variant cuda if you know better."
                    $resolvedVariant = 'cpu'
                }
            } else {
                $resolvedVariant = 'cpu'
            }
        } catch { $resolvedVariant = 'cpu' }
    } else {
        $resolvedVariant = 'cpu'
    }
}
Write-Ok "Selected variant: $resolvedVariant"

# --- 4. Hosts file entry ---
Write-Step "Hosts file (127.0.0.1 phoresis)"
$hostsPath = "$env:windir\System32\drivers\etc\hosts"
$hostsContent = Get-Content -Path $hostsPath -Raw
if ($hostsContent -notmatch '\bphoresis\b') {
    Add-Content -Path $hostsPath -Value "`n127.0.0.1`tphoresis"
    ipconfig /flushdns | Out-Null
    Write-Ok "Added 127.0.0.1 phoresis"
} else {
    Write-Ok "Already configured"
}

# --- 4b. Storage paths ---
Write-Step "Storage paths"
$mediaDir = Join-Path $DataDir 'media'
if (-not (Test-Path $mediaDir)) {
    New-Item -ItemType Directory -Path $mediaDir -Force | Out-Null
    Write-Ok "Created $mediaDir"
} else {
    Write-Ok "Using existing $mediaDir"
}

# Free-space check on the drive containing $DataDir
$driveLetter = (Split-Path -Qualifier $DataDir).TrimEnd(':')
$drive = Get-PSDrive -Name $driveLetter -ErrorAction SilentlyContinue
if ($drive) {
    $freeGB = [math]::Round($drive.Free / 1GB, 1)
    if ($freeGB -lt 1) {
        Write-Err "Drive $driveLetter`: has only $freeGB GB free - need at least 1 GB to start, 5+ GB recommended."
        exit 1
    } elseif ($freeGB -lt 5) {
        Write-Warn "Drive $driveLetter`: has only $freeGB GB free - 5+ GB recommended for gel image storage."
    } else {
        Write-Ok "Drive $driveLetter`: has $freeGB GB free"
    }
}

# Migrate from a previous named-volume install if it exists
$oldVolume = (& docker volume ls -q --filter "name=phoresis_phoresis_media" 2>$null).Trim()
if ($oldVolume) {
    Write-Warn "Detected legacy phoresis_media named volume - migrating contents to $mediaDir"
    $mediaDirForward = $mediaDir -replace '\\', '/'
    & docker run --rm `
        -v phoresis_phoresis_media:/src:ro `
        -v "${mediaDirForward}:/dst" `
        alpine:3 sh -c "cp -a /src/. /dst/ 2>/dev/null || true"
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Migration complete - the old volume can be deleted with: docker volume rm phoresis_phoresis_media"
    } else {
        Write-Warn "Migration had issues (exit $LASTEXITCODE). Old volume preserved."
    }
}

# --- 5. .env generation ---
Write-Step ".env"
$envPath = Join-Path $Script:RepoRoot '.env'
if (Test-Path $envPath) {
    Write-Sub ".env already exists - keeping it (delete to regenerate)"
} else {
    Write-Sub "Generating .env interactively"
    $adminEmail = Read-Host "Admin email"
    $adminPwdSecure = Read-Host "Admin password" -AsSecureString
    $adminPwd = ConvertFrom-SecureToPlain -Secure $adminPwdSecure
    $userEmail  = Read-Host "Primary lab user email"
    $userPwdSecure = Read-Host "Primary lab user password" -AsSecureString
    $userPwd = ConvertFrom-SecureToPlain -Secure $userPwdSecure
    $userName   = Read-Host "Primary lab user full name"

    $secret = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 50 | ForEach-Object { [char]$_ })

    $envMap = @{
        DJANGO_SETTINGS_MODULE   = 'phoresis.settings.prod'
        DJANGO_SECRET_KEY        = $secret
        DJANGO_DEBUG             = 'false'
        DJANGO_ALLOWED_HOSTS     = 'phoresis,localhost,127.0.0.1'
        DB_NAME                  = 'phoresis'
        DB_USER                  = 'phoresis'
        DB_PASSWORD              = 'phoresis'
        DB_PORT                  = '5432'
        REDIS_HOST               = 'redis'
        REDIS_PORT               = '6379'
        ADMIN_EMAIL              = $adminEmail
        ADMIN_PASSWORD           = $adminPwd
        PRIMARY_USER_EMAIL       = $userEmail
        PRIMARY_USER_PASSWORD    = $userPwd
        PRIMARY_USER_FULL_NAME   = $userName
        PHORESIS_IMAGE_VARIANT   = $resolvedVariant
        PHORESIS_MEDIA_DIR        = ($mediaDir -replace '\\', '/')
        TZ                       = 'Europe/Brussels'
    }
    Write-EnvFile -Path $envPath -Map $envMap
    Write-Ok ".env written with $resolvedVariant variant"
}

# --- 6. docker compose pull + up ---
Write-Step "Pulling Phoresis images from ghcr.io"
$composeArgs = Get-ComposeArgs -WithGpu:($resolvedVariant -eq 'cuda')
& docker compose @composeArgs pull
if ($LASTEXITCODE -ne 0) {
    Write-Err "docker compose pull failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}
Write-Ok "Images pulled"

Write-Step "Starting the stack"
& docker compose @composeArgs up -d
if ($LASTEXITCODE -ne 0) {
    Write-Err "docker compose up failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

# --- 7. Wait for healthcheck ---
Write-Step "Waiting for https://phoresis/healthz/live/ (max 90s)"
if (Wait-HttpOk -Url 'https://phoresis/healthz/live/' -TimeoutSeconds 90) {
    Write-Ok "Stack healthy"
} else {
    Write-Err "Healthcheck timed out. Run: docker compose $($composeArgs -join ' ') logs"
    exit 1
}

# --- 8. Trust Caddy CA (best-effort) ---
Write-Step "Trusting Caddy's internal CA"
try {
    $caddyContainer = (docker compose @composeArgs ps -q caddy).Trim()
    if ($caddyContainer) {
        $tmpCa = Join-Path $env:TEMP "phoresis-caddy-root.crt"
        docker exec $caddyContainer cat /data/caddy/pki/authorities/local/root.crt > $tmpCa
        if (Test-Path $tmpCa) {
            Import-Certificate -FilePath $tmpCa -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
            Remove-Item $tmpCa -Force
            Write-Ok "Caddy root CA trusted (browser will accept https://phoresis/)"
        }
    }
} catch {
    Write-Warn "Could not auto-trust Caddy CA. The browser will show a security warning the first time - accept it manually."
}

# --- 9. Desktop shortcut ---
Write-Step "Creating desktop shortcut"
$desktop  = [Environment]::GetFolderPath('Desktop')
$shortcut = Join-Path $desktop 'Phoresis.lnk'
$startScript = Join-Path $Script:RepoRoot 'scripts\start.ps1'
$iconPath = Join-Path $Script:RepoRoot 'assets\icons\phoresis.ico'

$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($shortcut)
$lnk.TargetPath = "powershell.exe"
$lnk.Arguments  = "-ExecutionPolicy Bypass -File `"$startScript`""
$lnk.WorkingDirectory = $Script:RepoRoot
if (Test-Path $iconPath) { $lnk.IconLocation = $iconPath }
$lnk.Description = "Phoresis - Gel Electrophoresis Analyzer"
$lnk.Save()
Write-Ok "Desktop shortcut: $shortcut"

# --- 10. Open browser ---
if (-not $SkipBrowserOpen) {
    Write-Step "Opening https://phoresis/"
    Start-Process 'https://phoresis/'
}

Write-Host ""
Write-Host "  Install complete. Welcome to Phoresis." -ForegroundColor Green
Write-Host ""
