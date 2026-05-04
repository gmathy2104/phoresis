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

    [switch]$SkipBrowserOpen,

    # Postgres port. Default 5432, but override when an existing Postgres
    # (e.g. PG16) already owns 5432 and the new Phoresis-targeted PG17
    # ended up on 5433.
    [int]$DBPort = 5432

    # NOTE: -DataDir was removed in v1.0.37 -- media now lives in the
    # Docker-managed named volume `phoresis_phoresis_media`, not a host
    # path. Backup with scripts/backup-media.ps1, restore with
    # scripts/restore-media.ps1.
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

# --- 0b. Git LFS (ML models) ---
# The SAM band-detection models (mobilesam_decoder.onnx, mobile_sam.pt, ...)
# live in src/gel_analyzer/static/gel_analyzer/ml/sam/ and are tracked via
# Git LFS. A `git clone` on a host without git-lfs gets ~134-byte pointer
# files instead of the real ~40 MB binaries -- and the worker silently
# crashes on the first band-detection task with a FileNotFoundError or
# "not a valid model" deep in onnxruntime.
#
# Detect this and run `git lfs install` + `git lfs pull` automatically.
Write-Step "Git LFS (ML model binaries)"
$samModel = Join-Path $Script:RepoRoot 'src\gel_analyzer\static\gel_analyzer\ml\sam\mobile_sam.pt'
if (-not (Test-Path $samModel)) {
    Write-Err "Expected ML model not found at $samModel -- is this a Phoresis clone?"
    exit 1
}
$samSize = (Get-Item $samModel).Length
if ($samSize -lt 1MB) {
    Write-Sub "ML models look like LFS pointer files (mobile_sam.pt is $samSize bytes -- expected >40 MB)"
    $gitLfs = Get-Command 'git-lfs' -ErrorAction SilentlyContinue
    if (-not $gitLfs) {
        # Try git lfs subcommand (older installs expose it that way)
        try { & git lfs version | Out-Null } catch { }
        if ($LASTEXITCODE -ne 0) {
            Write-Sub "git-lfs not installed. Installing via winget..."
            $winget = Resolve-Winget
            if (-not $winget) {
                Write-Err "winget unavailable. Install Git LFS manually: https://git-lfs.com/"
                exit 1
            }
            & $winget install --silent --accept-package-agreements --accept-source-agreements GitHub.GitLFS
            if ($LASTEXITCODE -ne 0) {
                Write-Err "Failed to install Git LFS via winget (exit $LASTEXITCODE)"
                exit 1
            }
            Write-Ok "Git LFS installed"
        }
    }
    Write-Sub "Initializing git lfs hooks + fetching LFS objects..."
    Push-Location $Script:RepoRoot
    try {
        & git lfs install --local
        & git lfs pull
        if ($LASTEXITCODE -ne 0) {
            Write-Err "git lfs pull failed (exit $LASTEXITCODE)"
            exit 1
        }
    } finally { Pop-Location }

    $samSize = (Get-Item $samModel).Length
    if ($samSize -lt 1MB) {
        Write-Err "After git lfs pull, mobile_sam.pt is still only $samSize bytes. LFS objects might not be available on the remote."
        exit 1
    }
    Write-Ok "ML models pulled via LFS (mobile_sam.pt: $([math]::Round($samSize/1MB,1)) MB)"
} else {
    Write-Ok "ML models present ($([math]::Round($samSize/1MB,1)) MB sample)"
}

# --- 1. Docker Desktop ---
Write-Step "Docker Desktop"
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    $winget = Resolve-Winget
    if (-not $winget) {
        Write-Err "winget is not available on this elevated session."
        Write-Sub "Install Docker Desktop manually: https://www.docker.com/products/docker-desktop/"
        Write-Sub "Then re-run this script."
        exit 1
    }
    Write-Sub "Installing Docker Desktop via winget..."
    & $winget install --silent --accept-package-agreements --accept-source-agreements Docker.DockerDesktop
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
# If psql isn't on PATH, also probe the standard install location -- Postgres
# 17's installer adds bin to PATH at install time but only takes effect in
# new shells. A re-run within the same shell would otherwise loop.
if (-not $psql) {
    $stdPath = "C:\Program Files\PostgreSQL\17\bin\psql.exe"
    if (Test-Path $stdPath) {
        Write-Warn "psql found at $stdPath but not on PATH. Adding it for this session."
        $env:PATH = "C:\Program Files\PostgreSQL\17\bin;" + $env:PATH
        $psql = Get-Command psql -ErrorAction SilentlyContinue
    }
}
if (-not $psql) {
    $winget = Resolve-Winget
    if (-not $winget) {
        Write-Err "PostgreSQL 17 is not installed and winget is not available."
        Write-Sub "Install Postgres 17 manually:"
        Write-Sub "  1. Download: https://www.postgresql.org/download/windows/"
        Write-Sub "  2. Run the EDB installer; remember the 'postgres' superuser password."
        Write-Sub "  3. Either tick 'Add to PATH' at end of install, or add"
        Write-Sub "     'C:\Program Files\PostgreSQL\17\bin' to your system PATH."
        Write-Sub "  4. Open a fresh admin PowerShell and re-run this script."
        exit 1
    }
    Write-Sub "Installing PostgreSQL 17 via winget..."
    & $winget install --silent --accept-package-agreements --accept-source-agreements PostgreSQL.PostgreSQL.17
    Write-Warn "Postgres installed. Set the 'postgres' user password during install if prompted."
    Write-Warn "Open a fresh admin PowerShell and re-run this script (PATH refresh)."
    exit 0
}
Write-Ok "psql present ($(psql --version))"

# Create phoresis DB + user (idempotent)
Write-Sub "Provisioning 'phoresis' database + user on port $DBPort"
if ($DBPort -ne 5432) {
    Write-Sub "Non-default port detected -- make sure Postgres 17 is reachable at 127.0.0.1:$DBPort"
}
$pgPassword = Read-Host "Postgres superuser ('postgres') password (port $DBPort)" -AsSecureString
$pgPasswordPlain = ConvertFrom-SecureToPlain -Secure $pgPassword

$env:PGPASSWORD = $pgPasswordPlain
# 1. Role (idempotent via DO block)
$roleSql = @"
DO `$`$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'phoresis') THEN
      CREATE ROLE phoresis WITH LOGIN PASSWORD 'phoresis' SUPERUSER;
   END IF;
END
`$`$;
"@
$roleSql | psql -U postgres -h 127.0.0.1 -p $DBPort -d postgres

# 2. Database (CREATE DATABASE can't run inside a DO block -- check then create)
$dbExists = & psql -U postgres -h 127.0.0.1 -p $DBPort -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='phoresis'"
if ($dbExists -ne '1') {
    & psql -U postgres -h 127.0.0.1 -p $DBPort -d postgres -c "CREATE DATABASE phoresis OWNER phoresis"
}
$env:PGPASSWORD = $null
Write-Ok "phoresis DB + user ready on port $DBPort"

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
# Don't trust a string match -- a stale comment with "phoresis" or a
# half-wiped previous install can fool the regex. Resolve the hostname
# instead: if Windows DNS can answer with 127.0.0.1, we're good. Anything
# else (NXDOMAIN, wrong IP) -> rewrite the hosts line.
$resolved = $null
try {
    $resolved = [System.Net.Dns]::GetHostAddresses("phoresis") | ForEach-Object { $_.IPAddressToString }
} catch { $resolved = $null }

if ($resolved -contains '127.0.0.1') {
    Write-Ok "Already resolves to 127.0.0.1"
} else {
    # Strip any existing phoresis line (comment, wrong IP, etc.) before adding ours.
    $newContent = (Get-Content -Path $hostsPath) | Where-Object { $_ -notmatch '\bphoresis\b' }
    [System.IO.File]::WriteAllLines($hostsPath, $newContent, [System.Text.UTF8Encoding]::new($false))
    Add-Content -Path $hostsPath -Value "127.0.0.1`tphoresis"
    ipconfig /flushdns | Out-Null
    Write-Ok "Added 127.0.0.1 phoresis (replaced any stale entry)"
}

# --- 4b. Media volume + storage check ---
# Media lives in `phoresis_phoresis_media` (Docker named volume, since v1.0.37
# -- bind mounts misbehaved on Docker Desktop WSL2). Declared `external: true`
# in compose.yml so `docker compose down -v` will NOT remove it; we create it
# here ahead of compose up. Idempotent: `docker volume create` succeeds when
# the volume already exists.
Write-Step "Media volume"
& docker volume create phoresis_phoresis_media 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Ok "phoresis_phoresis_media ready (created or already existed)"
} else {
    Write-Err "docker volume create failed (exit $LASTEXITCODE)"
    exit 1
}

# Free-space check on the drive where Docker Desktop's VHDX lives by default.
Write-Step "Storage check"
$dockerDrive = ($env:USERPROFILE.Substring(0, 1)).ToUpper()
$drive = Get-PSDrive -Name $dockerDrive -ErrorAction SilentlyContinue
if ($drive) {
    $freeGB = [math]::Round($drive.Free / 1GB, 1)
    if ($freeGB -lt 1) {
        Write-Err "Drive $dockerDrive`: has only $freeGB GB free - need at least 1 GB to start, 5+ GB recommended."
        exit 1
    } elseif ($freeGB -lt 5) {
        Write-Warn "Drive $dockerDrive`: has only $freeGB GB free - 5+ GB recommended for gel image storage."
    } else {
        Write-Ok "Drive $dockerDrive`: has $freeGB GB free (media stored in Docker named volume)"
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
        DB_PORT                  = "$DBPort"
        REDIS_HOST               = 'redis'
        REDIS_PORT               = '6379'
        ADMIN_EMAIL              = $adminEmail
        ADMIN_PASSWORD           = $adminPwd
        PRIMARY_USER_EMAIL       = $userEmail
        PRIMARY_USER_PASSWORD    = $userPwd
        PRIMARY_USER_FULL_NAME   = $userName
        PHORESIS_IMAGE_VARIANT   = $resolvedVariant
        TZ                       = 'Europe/Brussels'
    }
    Write-EnvFile -Path $envPath -Map $envMap
    Write-Ok ".env written with $resolvedVariant variant"
}

# --- 6. Get the images ---
# CPU images are pulled from ghcr.io (built by release.yml CI).
# CUDA images are NOT shipped via CI (avoids GitHub-runner disk/time ceilings);
# they're built locally on the user's GPU machine -- fast on a workstation
# with a real GPU, and the cache mounts in the Dockerfiles make rebuilds cheap.
$composeArgs = Get-ComposeArgs -WithGpu:($resolvedVariant -eq 'cuda')
if ($resolvedVariant -eq 'cuda') {
    Write-Step "Building CUDA images locally (one-time, ~15-25 min on first run)"
    Write-Sub "GPU users build locally so we can ship cu128 + Blackwell support"
    Write-Sub "without overflowing GitHub-hosted runner disks. Subsequent rebuilds"
    Write-Sub "(after a phoresis update) are much faster thanks to the layer cache."
    & docker compose @composeArgs build --build-arg TORCH_VARIANT=cuda
    if ($LASTEXITCODE -ne 0) {
        Write-Err "docker compose build (cuda) failed (exit $LASTEXITCODE)"
        exit $LASTEXITCODE
    }
    Write-Ok "CUDA images built"
} else {
    Write-Step "Pulling Phoresis CPU images from ghcr.io"
    & docker compose @composeArgs pull
    if ($LASTEXITCODE -ne 0) {
        Write-Err "docker compose pull failed (exit $LASTEXITCODE)"
        exit $LASTEXITCODE
    }
    Write-Ok "Images pulled"
}

Write-Step "Starting the stack"
& docker compose @composeArgs up -d
if ($LASTEXITCODE -ne 0) {
    Write-Err "docker compose up failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

# --- 7. Wait for healthcheck ---
# 240s timeout: covers the worst case where `docker compose up -d` recreates
# the web container (e.g. after a rebuild on update). Web entrypoint takes
# 30-90s (migrate + collectstatic post-processing of ~700 files + seeds +
# gunicorn boot), and Caddy's active health check needs another ~10s to
# detect the upstream is back.
Write-Step "Waiting for https://phoresis/healthz/live/ (max 240s)"
if (Wait-HttpOk -Url 'https://phoresis/healthz/live/' -TimeoutSeconds 240) {
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
