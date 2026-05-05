<#
.SYNOPSIS
    Phoresis DEVSTACK manager — Postgres + Redis + Celery worker/beat in Docker
    for native-Windows Django dev (manage.py runserver runs on the host).

.DESCRIPTION
    Wraps `docker compose -f docker/compose.devstack.yml` with sensible
    subcommands so you don't have to remember the flags. The devstack is
    completely independent from the prod stack (`docker-compose.yml`); they
    can run side-by-side without colliding (different compose project name,
    different network, different host port mappings).

.PARAMETER Action
    up        Start the devstack (Postgres + Redis + worker + beat).
    down      Stop the devstack. Volumes preserved (DB + media survive).
    logs      Tail logs from all devstack services.
    ps        List devstack containers + their status.
    psql      Open a psql shell against the dev database.
    reset-db  Stop + remove the postgres data volume + restart. ALL DEV
              DATA IS LOST. Asks for confirmation.
    restart-worker  Restart only the worker (after editing task code).

.PARAMETER Variant
    cpu (default) | cuda. Only meaningful with `up`.
    `cpu`  pulls/uses ghcr.io/gmathy2104/phoresis-app:latest-cpu (~9.5 GB) —
           plenty for dev work that doesn't exercise GPU code paths.
    `cuda` uses ghcr.io/gmathy2104/phoresis-app:latest-cuda (~19 GB, must be
           built locally — not shipped via CI) AND attaches the host's NVIDIA
           GPU(s) to the worker container so torch.cuda.is_available() returns
           True inside Celery tasks. Requires NVIDIA Container Toolkit on
           the WSL2 distro.

.EXAMPLE
    .\scripts\devstack.ps1 up
    . .\scripts\dev-env.ps1
    .venv\Scripts\python.exe manage.py migrate
    .venv\Scripts\python.exe manage.py runserver

.EXAMPLE
    .\scripts\devstack.ps1 up -Variant cuda

.EXAMPLE
    .\scripts\devstack.ps1 logs

.EXAMPLE
    .\scripts\devstack.ps1 reset-db
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet('up', 'down', 'logs', 'ps', 'psql', 'reset-db', 'restart-worker')]
    [string]$Action,

    [ValidateSet('cpu', 'cuda')]
    [string]$Variant = 'cpu'
)

$ErrorActionPreference = 'Stop'

$Script:RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$composeFile    = Join-Path $Script:RepoRoot 'docker\compose.devstack.yml'
$gpuOverlayFile = Join-Path $Script:RepoRoot 'docker\compose.devstack.gpu.yml'

if (-not (Test-Path $composeFile)) {
    Write-Error "compose file not found: $composeFile"
    exit 1
}

# Ensure the local _dev_media dir exists before compose tries to mount it
# (otherwise Docker silently creates it as root-owned, which the worker can't
# write to under UID 1000).
$devMedia = Join-Path $Script:RepoRoot '_dev_media'
if (-not (Test-Path $devMedia)) {
    New-Item -ItemType Directory -Path $devMedia -Force | Out-Null
    Write-Host "Created $devMedia" -ForegroundColor DarkGray
}

# Build the compose -f arg list. For `up -Variant cuda`, we layer the GPU
# overlay AND set the env var so the cuda image tag is selected. For all
# other actions (down/logs/etc), we use the same overlay set so compose can
# correctly identify the existing project state.
$composeArgs = @('-f', $composeFile)
if ($Variant -eq 'cuda') {
    if (-not (Test-Path $gpuOverlayFile)) {
        Write-Error "GPU overlay file not found: $gpuOverlayFile"
        exit 1
    }
    $composeArgs += @('-f', $gpuOverlayFile)
    $env:PHORESIS_APP_IMAGE = 'ghcr.io/gmathy2104/phoresis-app:latest-cuda'
}

switch ($Action) {
    'up' {
        Write-Host "==> Starting Phoresis devstack (variant: $Variant)" -ForegroundColor Cyan
        if ($Variant -eq 'cuda') {
            # Sanity check: the cuda image must already exist locally (not on GHCR).
            $hasCudaImage = (& docker image inspect ghcr.io/gmathy2104/phoresis-app:latest-cuda 2>$null)
            if (-not $hasCudaImage) {
                Write-Host "  [WARN] phoresis-app:latest-cuda not found locally." -ForegroundColor Yellow
                Write-Host "  Build it first with: .\scripts\install.ps1 -Variant cuda" -ForegroundColor Yellow
                Write-Host "  (Or set PHORESIS_APP_IMAGE to a tag you do have.)" -ForegroundColor Yellow
                Write-Host ""
            }
        }
        & docker compose @composeArgs up -d
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Host ""
        Write-Host "Devstack is up. Next steps:" -ForegroundColor Green
        Write-Host "  1. Load env vars in your shell:  . .\scripts\dev-env.ps1"
        Write-Host "  2. Run migrations:                .venv\Scripts\python.exe manage.py migrate"
        Write-Host "  3. Start the dev server:          .venv\Scripts\python.exe manage.py runserver"
        Write-Host "  4. (Optional) CSS watch:          npm run watch:css"
        Write-Host ""
        Write-Host "Postgres: 127.0.0.1:15432  |  Redis: 127.0.0.1:16379  |  Media: $devMedia"
        if ($Variant -eq 'cuda') {
            Write-Host ""
            Write-Host "Worker has GPU passthrough. Inside the container:" -ForegroundColor Cyan
            Write-Host "  docker exec phoresis-dev-worker-1 python -c 'import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))'"
        }
    }
    'down' {
        Write-Host "==> Stopping Phoresis devstack (volumes preserved)" -ForegroundColor Cyan
        & docker compose @composeArgs down
    }
    'logs' {
        & docker compose @composeArgs logs -f --tail=50
    }
    'ps' {
        & docker compose @composeArgs ps
    }
    'psql' {
        # Use the host-exposed port so we don't need psql installed inside the
        # container — relies on the user's native PostgreSQL client.
        $psql = "C:\Program Files\PostgreSQL\17\bin\psql.exe"
        if (-not (Test-Path $psql)) {
            $psql = 'psql'   # fallback to PATH
        }
        $env:PGPASSWORD = 'phoresis'
        & $psql -U phoresis -h 127.0.0.1 -p 15432 -d phoresis
        $env:PGPASSWORD = $null
    }
    'reset-db' {
        Write-Host "WARNING: This will DROP the dev database and all its data." -ForegroundColor Yellow
        $confirm = Read-Host "Type 'yes' to proceed"
        if ($confirm -ne 'yes') {
            Write-Host "Aborted."
            exit 0
        }
        Write-Host "==> Stopping devstack" -ForegroundColor Cyan
        & docker compose @composeArgs down -v
        Write-Host "==> Restarting (postgres will re-init on first boot)" -ForegroundColor Cyan
        & docker compose @composeArgs up -d
        Write-Host "Done. Run migrations against the fresh DB:" -ForegroundColor Green
        Write-Host "  . .\scripts\dev-env.ps1"
        Write-Host "  .venv\Scripts\python.exe manage.py migrate"
    }
    'restart-worker' {
        Write-Host "==> Restarting worker (picks up edited task code)" -ForegroundColor Cyan
        & docker compose @composeArgs restart worker
    }
}
