<#
.SYNOPSIS
    Start the Phoresis stack and open the browser.

.DESCRIPTION
    Wired to the desktop shortcut. Idempotent - can be run while the stack
    is already up (returns immediately).
#>
[CmdletBinding()]
param(
    [switch]$SkipBrowser
)

. "$PSScriptRoot\_common.ps1"

$envMap = Read-EnvFile (Join-Path $Script:RepoRoot '.env')
$variant = $envMap['PHORESIS_IMAGE_VARIANT']
if (-not $variant) { $variant = 'cpu' }

Write-Step "Starting Phoresis ($variant variant)"
$composeArgs = Get-ComposeArgs -WithGpu:($variant -eq 'cuda')

& docker compose @composeArgs up -d
if ($LASTEXITCODE -ne 0) {
    Write-Err "docker compose up failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

Write-Step "Waiting for https://phoresis/healthz/live/"
if (-not (Wait-HttpOk -Url 'https://phoresis/healthz/live/' -TimeoutSeconds 60)) {
    Write-Warn "Healthcheck timed out (60s). The stack may still be warming up."
}

if (-not $SkipBrowser) {
    Start-Process 'https://phoresis/'
}
Write-Ok "Phoresis is running at https://phoresis/"
