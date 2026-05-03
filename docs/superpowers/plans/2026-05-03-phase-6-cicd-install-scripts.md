# Phoresis — Phase 6 (CI/CD + Install Scripts) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate the build/release pipeline (GitHub Actions matrix build for `(cpu,cuda) × (web,worker) = 4` images, GHCR push, conventional-commit-driven CHANGELOG, GitHub Release creation) and ship six PowerShell scripts that take a clean Windows 11 laptop from "nothing installed" to "`https://phoresis/` is live" in under 5 minutes — `install.ps1` / `start.ps1` / `stop.ps1` / `update.ps1` / `backup.ps1` / `restore.ps1`. Tagged `v0.6.0`.

**Architecture:** Two parallel workflows in `.github/workflows/`:
- **`ci.yml`** (extended from Phase 1) — runs on every PR + push to `main`: lint, test, e2e (chromium only), Trivy CVE scan on the built images.
- **`release.yml`** (new) — runs on `v*.*.*` tag: builds the 4-variant image matrix, pushes to `ghcr.io/gmathy2104/phoresis-{web,worker}:{vX.Y.Z,latest}-{cpu,cuda}`, generates release notes from Conventional Commits, creates a GitHub Release.

The PowerShell scripts use only stdlib + `winget` + `docker` CLI — no external PowerShell modules. They're idempotent, all support `-WhatIf` for dry-run inspection, and surface errors via `$LASTEXITCODE`.

**Tech Stack delta:** No new Python deps. Adds `release-please-action` (GitHub Action for semver-driven release automation), `aquasecurity/trivy-action` (CVE scanner), `docker/build-push-action` (image build + push). PowerShell scripts target PowerShell 5.1+ (the Windows 11 default).

**Image visibility decision:** Spec §13 deferred to this phase — **defaulting to PUBLIC** GHCR images. The image content is open-source code + open-weights ML models (MobileSAM, YOLO) — no secrets, no proprietary data. Public eliminates the `docker login ghcr.io` friction in `install.ps1` and lets Watchtower auto-pull without credential management. If the user changes their mind, the override is documented at the bottom of `install.ps1` (one-line `docker login` + a single `private` flag in `.env`).

**Source repo for ports:** No port from `ds-hub-django` here — the CI/CD and install scripts are Phoresis-specific. Reference for PowerShell idioms only.

---

## Build Order Rationale

1. **Conventional Commits + CHANGELOG infra** (Task 1) — must come before the release workflow, which consumes it.
2. **Extend `ci.yml`** (Task 2) — full test matrix + Trivy scan before any release pipeline runs.
3. **`release.yml`** (Task 3) — image matrix build + GHCR push + GitHub Release; depends on Tasks 1-2.
4. **`install.ps1`** (Task 4) — the entry point for non-technical end users; biggest, most testable script.
5. **`start.ps1` + `stop.ps1`** (Task 5) — daily scripts; trivial wrappers around `docker compose`.
6. **`update.ps1`** (Task 6) — manual update + `-Rollback` flag.
7. **`backup.ps1` + `restore.ps1`** (Task 7) — `pg_dump` + media tar; rotated retention; interactive restore.
8. **Watchtower credentials story** (Task 8) — public-image documented; private-image fallback noted.
9. **Clean-machine validation** (Task 9) — walk through `install.ps1` on a freshly imaged box (or VM snapshot rollback).
10. **Tag v0.6.0** (Task 10) — final commit + tag.

---

## File Structure (additions to Phase 5)

```
.github/
├── release-please-config.json        # release-please configuration
├── .release-please-manifest.json     # version state
└── workflows/
    ├── ci.yml                        # EXTENDED from Phase 1
    └── release.yml                   # NEW

scripts/
├── install.ps1                       # NEW: clean-machine installer
├── start.ps1                         # NEW: daily up + browser
├── stop.ps1                          # NEW: daily down
├── update.ps1                        # NEW: pull + up; -Rollback flag
├── backup.ps1                        # NEW: pg_dump + media tar
├── restore.ps1                       # NEW: interactive restore
└── _common.ps1                       # NEW: shared helpers (logging, env loading)

CHANGELOG.md                          # NEW: auto-generated from Conventional Commits
.gitignore                            # extended: ignore *.bak, /scripts/.tmp/
```

---

## Task 1: Conventional Commits + CHANGELOG infrastructure

**Files:**
- Create: `.github/release-please-config.json`
- Create: `.github/.release-please-manifest.json`
- Create: `CHANGELOG.md` (initial scaffold)

[release-please](https://github.com/googleapis/release-please) reads the commit history since the last release, decides the next semver bump (`feat:` → minor, `fix:` → patch, `feat!:` / `BREAKING CHANGE:` → major), opens a PR with the bumped version + auto-generated CHANGELOG entries, and on merge tags `vX.Y.Z` — which fires `release.yml` (Task 3). All tooling lives in GitHub Actions; nothing to install locally.

- [ ] **Step 1: Create `.github/release-please-config.json`**

```json
{
  "release-type": "python",
  "packages": {
    ".": {
      "package-name": "phoresis",
      "release-type": "python",
      "include-component-in-tag": false,
      "draft": false,
      "prerelease": false,
      "extra-files": [
        {
          "type": "toml",
          "path": "pyproject.toml",
          "jsonpath": "$.project.version"
        }
      ],
      "changelog-sections": [
        { "type": "feat",     "section": "Features" },
        { "type": "fix",      "section": "Bug fixes" },
        { "type": "perf",     "section": "Performance" },
        { "type": "refactor", "section": "Refactoring" },
        { "type": "docs",     "section": "Documentation", "hidden": false },
        { "type": "test",     "section": "Tests", "hidden": true },
        { "type": "build",    "section": "Build", "hidden": false },
        { "type": "ci",       "section": "CI", "hidden": true },
        { "type": "chore",    "section": "Chores", "hidden": true }
      ]
    }
  }
}
```

- [ ] **Step 2: Create `.github/.release-please-manifest.json`**

Pin the current version explicitly so release-please starts from v0.5.0 (where Phase 5 left off):

```json
{
  ".": "0.5.0"
}
```

- [ ] **Step 3: Create `CHANGELOG.md` scaffold**

```markdown
# Changelog

All notable changes to Phoresis are documented here.

This file is auto-generated from [Conventional Commits](https://www.conventionalcommits.org/)
by [release-please](https://github.com/googleapis/release-please) on every tagged release.

For a human-readable explanation of each phase milestone, see `docs/specs/`.

---

## [Unreleased]

### Phase 6 — CI/CD + install scripts (in progress)

- See `docs/superpowers/plans/2026-05-03-phase-6-cicd-install-scripts.md`.

## [0.5.0] - 2026-MM-DD

### Phase 5 — Docker + Caddy packaging

- Healthz endpoints (`/healthz/`, `/healthz/celery/`, `/healthz/live/`).
- `seed_groups` management command.
- Multi-stage `Dockerfile.web` and `Dockerfile.worker` (CPU + CUDA variants).
- `Caddyfile` with `tls internal`, HSTS, static/media file serving.
- Six-service `docker-compose.yml` (Caddy / web / worker / scheduler / Redis / Watchtower).
- `compose.gpu.yml` override for NVIDIA Container Toolkit.

## [0.4.0] - 2026-MM-DD

### Phase 4 — Heavy viewers + DRF API + e2e

- 6 DRF viewsets + ~50 non-DRF JSON endpoints.
- Annotation, densitometry, comparison heavy viewers in Tailwind chrome.
- Report builders (docx / xlsx / pptx).
- Playwright golden-path e2e.

## [0.3.0] - 2026-MM-DD

### Phase 3 — Frontend foundation

- Tailwind 4 + design tokens + 9 component templatetags.
- Lucide sprite + 8 custom SVG icons.
- Alpine stores (theme / toast / modal / palette) + HTMX config.
- Layout shell (sidebar / topbar / command palette).
- Theme switcher with `UserProfile.theme` persistence.
- Phoresis app icon.
- Refonte of login / profile / dashboard / image and analysis shell pages.

## [0.2.0] - 2026-MM-DD

### Phase 2 — Models & services extraction

- 14 models cleaned of `process_sample`, FKs to `accounts.User`, +`sample_metadata`.
- All scientific services preserved (band_detection, calibration, densitometry, SAM, file_handler, scn_parser, template_learning, studio).
- 9 Celery tasks.
- ML models bundled (Git LFS).
- Admin ported.
- `seed_ladder_templates` + `create_initial_users` commands.

## [0.1.0] - 2026-MM-DD

### Phase 1 — Bootstrap & shims

- Django 5.2 project with split settings.
- `phoresis_core` (logging, celery, error handling, navigation registry).
- `accounts` app with custom `User` + `UserProfile` + 3 seeded groups.
- `dashboard` stub + `phoresis_ui` skeleton.
- pytest, ruff, pre-commit, GitHub Actions baseline CI.
```

- [ ] **Step 4: Commit**

```bash
git add .github/release-please-config.json .github/.release-please-manifest.json CHANGELOG.md
git commit -m "chore: add release-please config + initial CHANGELOG"
```

---

## Task 2: Extend `ci.yml` — full test matrix + Trivy

**Files:**
- Modify: `.github/workflows/ci.yml`

The Phase 1 baseline ran `ruff` + `pytest` against Postgres+Redis. Phase 6 extends with: Playwright e2e (Chromium), Tailwind build sanity, Trivy CVE scan on a built CPU image. Skips CUDA in CI (GitHub-hosted runners have no GPU + the build is too slow).

- [ ] **Step 1: Replace `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

env:
  DJANGO_SETTINGS_MODULE: phoresis.settings.test
  PYTHON_VERSION: "3.12"

jobs:

  # ───────────────────────── lint ─────────────────────────
  lint:
    name: Lint (ruff + djlint)
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - run: uv sync --extra dev
      - run: uv run ruff check .
      - run: uv run ruff format --check .

  # ───────────────────────── frontend build ─────────────────────────
  frontend:
    name: Frontend (Tailwind build sanity)
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20", cache: "npm" }
      - run: npm install
      - run: npm run build:css
      - name: Verify output.css
        run: |
          test -s src/phoresis_ui/static/phoresis_ui/css/output.css
          echo "output.css size: $(stat -c%s src/phoresis_ui/static/phoresis_ui/css/output.css) bytes"
      - uses: actions/upload-artifact@v4
        with:
          name: tailwind-css
          path: src/phoresis_ui/static/phoresis_ui/css/output.css
          if-no-files-found: error

  # ───────────────────────── unit + integration tests ─────────────────────────
  test:
    name: Tests (pytest, Postgres 17 + Redis 7)
    runs-on: ubuntu-24.04
    needs: [lint]
    services:
      postgres:
        image: postgres:17
        env:
          POSTGRES_DB: phoresis
          POSTGRES_USER: phoresis
          POSTGRES_PASSWORD: phoresis
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7
        ports: ['6379:6379']
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      DB_HOST: 127.0.0.1
      DB_NAME: phoresis
      DB_USER: phoresis
      DB_PASSWORD: phoresis
      REDIS_HOST: 127.0.0.1
    steps:
      - uses: actions/checkout@v4
        with: { lfs: true }
      - uses: astral-sh/setup-uv@v3
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - run: uv sync --extra dev
      - run: uv run python manage.py migrate --noinput
      - run: uv run pytest -v --create-db --cov=src --cov-report=xml
      - uses: codecov/codecov-action@v4
        if: ${{ secrets.CODECOV_TOKEN != '' }}
        with:
          token: ${{ secrets.CODECOV_TOKEN }}
          files: coverage.xml

  # ───────────────────────── e2e (Playwright Chromium) ─────────────────────────
  e2e:
    name: E2E (Playwright)
    runs-on: ubuntu-24.04
    needs: [test, frontend]
    services:
      postgres:
        image: postgres:17
        env: { POSTGRES_DB: phoresis_e2e, POSTGRES_USER: phoresis, POSTGRES_PASSWORD: phoresis }
        ports: ['5432:5432']
        options: --health-cmd pg_isready --health-interval 10s --health-timeout 5s --health-retries 5
      redis:
        image: redis:7
        ports: ['6379:6379']
        options: --health-cmd "redis-cli ping" --health-interval 10s --health-timeout 5s --health-retries 5
    env:
      DB_HOST: 127.0.0.1
      DB_NAME: phoresis_e2e
      DB_USER: phoresis
      DB_PASSWORD: phoresis
      REDIS_HOST: 127.0.0.1
    steps:
      - uses: actions/checkout@v4
        with: { lfs: true }
      - uses: astral-sh/setup-uv@v3
        with: { python-version: "${{ env.PYTHON_VERSION }}" }
      - run: uv sync --extra dev
      - run: uv run playwright install --with-deps chromium
      - uses: actions/download-artifact@v4
        with:
          name: tailwind-css
          path: src/phoresis_ui/static/phoresis_ui/css/
      - run: uv run pytest tests/e2e/ -m e2e -v

  # ───────────────────────── docker image build (smoke) ─────────────────────────
  build-cpu:
    name: Build CPU image (smoke)
    runs-on: ubuntu-24.04
    needs: [lint]
    steps:
      - uses: actions/checkout@v4
        with: { lfs: true }
      - uses: docker/setup-buildx-action@v3
      - name: Build phoresis-web (cpu)
        uses: docker/build-push-action@v6
        with:
          context: .
          file: docker/Dockerfile.web
          build-args: TORCH_VARIANT=cpu
          push: false
          tags: phoresis-web:ci-cpu
          cache-from: type=gha
          cache-to: type=gha,mode=max
          load: true
          outputs: type=docker
      - name: Build phoresis-worker (cpu)
        uses: docker/build-push-action@v6
        with:
          context: .
          file: docker/Dockerfile.worker
          build-args: TORCH_VARIANT=cpu
          push: false
          tags: phoresis-worker:ci-cpu
          cache-from: type=gha
          cache-to: type=gha,mode=max
          load: true
          outputs: type=docker

  # ───────────────────────── trivy CVE scan ─────────────────────────
  trivy:
    name: Trivy CVE scan
    runs-on: ubuntu-24.04
    needs: [build-cpu]
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - name: Rebuild web image (uses cache)
        uses: docker/build-push-action@v6
        with:
          context: .
          file: docker/Dockerfile.web
          build-args: TORCH_VARIANT=cpu
          push: false
          tags: phoresis-web:trivy
          cache-from: type=gha
          load: true
      - name: Trivy scan
        uses: aquasecurity/trivy-action@0.28.0
        with:
          image-ref: phoresis-web:trivy
          format: table
          severity: CRITICAL,HIGH
          exit-code: 1
          ignore-unfixed: true
          vuln-type: os,library
```

- [ ] **Step 2: Validate workflow syntax (optional)**

```bash
actionlint .github/workflows/ci.yml 2>&1 || echo "actionlint not installed — GitHub will validate on first push"
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: extend pipeline with frontend build, e2e, image build smoke, Trivy CVE scan"
```

---

## Task 3: `release.yml` — matrix build × ghcr push + GitHub Release

**Files:**
- Create: `.github/workflows/release.yml`

Triggered on `v*.*.*` tag (release-please opens the bump PR; merging it creates the tag). Builds the 4-variant matrix, pushes to GHCR with both versioned + `:latest` tags, attaches the CPU image's SBOM as a release asset.

- [ ] **Step 1: Create `.github/workflows/release.yml`**

```yaml
name: Release

on:
  push:
    tags: ['v*.*.*']
  workflow_dispatch:
    inputs:
      tag:
        description: "Tag to (re)build (e.g. v1.2.3)"
        required: true

permissions:
  contents: write
  packages: write
  id-token: write

env:
  REGISTRY: ghcr.io
  IMAGE_OWNER: gmathy2104

jobs:

  # ───────────────────────── release-please ─────────────────────────
  release-please:
    name: release-please (open or merge release PR)
    runs-on: ubuntu-24.04
    if: github.event_name == 'push' && startsWith(github.ref, 'refs/heads/main')
    outputs:
      release_created: ${{ steps.rp.outputs.release_created }}
      tag_name:        ${{ steps.rp.outputs.tag_name }}
    steps:
      - uses: googleapis/release-please-action@v4
        id: rp
        with:
          config-file: .github/release-please-config.json
          manifest-file: .github/.release-please-manifest.json

  # ───────────────────────── build + push (4-variant matrix) ─────────────────────────
  build-and-push:
    name: ${{ matrix.image }}-${{ matrix.variant }}
    runs-on: ubuntu-24.04
    if: startsWith(github.ref, 'refs/tags/v') || github.event_name == 'workflow_dispatch'
    strategy:
      fail-fast: false
      matrix:
        image:   [web, worker]
        variant: [cpu, cuda]
    steps:
      - uses: actions/checkout@v4
        with: { lfs: true }

      - name: Resolve tag (push event vs manual dispatch)
        id: tag
        run: |
          if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then
            echo "value=${{ inputs.tag }}" >> "$GITHUB_OUTPUT"
          else
            echo "value=${GITHUB_REF#refs/tags/}" >> "$GITHUB_OUTPUT"
          fi

      - uses: docker/setup-buildx-action@v3

      - uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build + push phoresis-${{ matrix.image }}:{tag,latest}-${{ matrix.variant }}
        uses: docker/build-push-action@v6
        with:
          context: .
          file: docker/Dockerfile.${{ matrix.image }}
          build-args: TORCH_VARIANT=${{ matrix.variant }}
          push: true
          tags: |
            ${{ env.REGISTRY }}/${{ env.IMAGE_OWNER }}/phoresis-${{ matrix.image }}:${{ steps.tag.outputs.value }}-${{ matrix.variant }}
            ${{ env.REGISTRY }}/${{ env.IMAGE_OWNER }}/phoresis-${{ matrix.image }}:latest-${{ matrix.variant }}
          cache-from: type=registry,ref=${{ env.REGISTRY }}/${{ env.IMAGE_OWNER }}/phoresis-${{ matrix.image }}:buildcache-${{ matrix.variant }}
          cache-to:   type=registry,ref=${{ env.REGISTRY }}/${{ env.IMAGE_OWNER }}/phoresis-${{ matrix.image }}:buildcache-${{ matrix.variant }},mode=max
          provenance: true
          sbom: true

  # ───────────────────────── attach SBOM to GitHub Release ─────────────────────────
  attach-assets:
    name: Attach SBOM + checksums to GitHub Release
    runs-on: ubuntu-24.04
    needs: [build-and-push]
    if: startsWith(github.ref, 'refs/tags/v')
    steps:
      - uses: actions/checkout@v4

      - name: Resolve tag
        id: tag
        run: echo "value=${GITHUB_REF#refs/tags/}" >> "$GITHUB_OUTPUT"

      - uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Pull SBOM (web cpu) and write to file
        run: |
          docker buildx imagetools inspect \
            ${{ env.REGISTRY }}/${{ env.IMAGE_OWNER }}/phoresis-web:${{ steps.tag.outputs.value }}-cpu \
            --format '{{ json .SBOM.SPDX }}' > sbom-web-cpu.json
          ls -lh sbom-web-cpu.json

      - name: Upload SBOM to release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ steps.tag.outputs.value }}
          files: sbom-web-cpu.json
          fail_on_unmatched_files: false
```

- [ ] **Step 2: Document the release flow in `CONTRIBUTING.md` (create if missing)**

Create `CONTRIBUTING.md` (or append if exists):

```markdown
# Contributing to Phoresis

## Release flow

1. Land changes on `main` using [Conventional Commits](https://www.conventionalcommits.org/):
   - `feat: ...` → minor version bump
   - `fix: ...` → patch bump
   - `feat!: ...` or `BREAKING CHANGE:` in body → major bump
2. `release-please` opens a PR titled "chore(main): release X.Y.Z" with the bumped version + auto-generated CHANGELOG entries.
3. Review and merge the PR.
4. Merging tags `vX.Y.Z` and triggers `release.yml`, which:
   - Builds 4 images: `(cpu, cuda) × (web, worker)`.
   - Pushes to `ghcr.io/gmathy2104/phoresis-{web,worker}:{vX.Y.Z, latest}-{cpu, cuda}`.
   - Creates a GitHub Release with auto-generated notes.
   - Attaches the CPU web image SBOM.
5. Watchtower (running on every Phoresis install) detects the new `:latest-{variant}` digest at 03:00 daily and self-updates.

## Manual rollback

Pin a specific image tag in `.env`:

```
PHORESIS_IMAGE_TAG=v0.4.0-cpu
```

Then run `scripts/update.ps1 -Rollback v0.4.0`.
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml CONTRIBUTING.md
git commit -m "ci: add release.yml (matrix build, ghcr.io push, GitHub Release with SBOM)"
```

---

## Task 4: `install.ps1` — clean-machine installer

**Files:**
- Create: `scripts/_common.ps1`
- Create: `scripts/install.ps1`

`install.ps1` is the most consequential script — it's what the primary user runs once on her laptop. The flow:

1. Check Windows 11 + admin elevation.
2. Install Docker Desktop (winget) if missing; start it; wait for the daemon.
3. Install Postgres 17 (winget) if missing; create `phoresis` DB + user.
4. Detect NVIDIA GPU (via `nvidia-smi`); pick CPU or CUDA variant.
5. Add `127.0.0.1 phoresis` to hosts file.
6. Generate `.env` interactively (prompt for admin/lab passwords).
7. `docker compose pull` + `up -d`.
8. Wait for `https://phoresis/healthz/live/` to return 200.
9. Trust Caddy's internal CA (so the browser stops nagging).
10. Open `https://phoresis/` in the default browser.
11. Create a desktop shortcut wired to `phoresis.ico`.

- [ ] **Step 1: Create `scripts/_common.ps1`** (shared helpers)

```powershell
<#
.SYNOPSIS
    Shared helpers for Phoresis PowerShell scripts.

.DESCRIPTION
    Loaded via `. "$PSScriptRoot\_common.ps1"` from each script.
    Provides logging primitives + .env reading + a few small utilities.

.NOTES
    Targets Windows PowerShell 5.1+ (Windows 11 default).
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------- logging ----------

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Sub {
    param([string]$Message)
    Write-Host "    $Message" -ForegroundColor DarkGray
}

function Write-Ok {
    param([string]$Message)
    Write-Host "    [OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "    [WARN] $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host "    [ERROR] $Message" -ForegroundColor Red
}

# ---------- .env helpers ----------

function Read-EnvFile {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path $Path)) { return @{} }
    $env = @{}
    Get-Content -Path $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#')) { return }
        $eq = $line.IndexOf('=')
        if ($eq -lt 1) { return }
        $key = $line.Substring(0, $eq).Trim()
        $val = $line.Substring($eq + 1).Trim()
        if ($val -match '^"(.*)"$' -or $val -match "^'(.*)'$") { $val = $matches[1] }
        $env[$key] = $val
    }
    return $env
}

function Write-EnvFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][hashtable]$Map
    )
    $lines = @("# Phoresis environment — generated by install.ps1")
    foreach ($k in $Map.Keys | Sort-Object) {
        $v = $Map[$k]
        if ($v -match '\s') { $v = '"' + $v + '"' }
        $lines += "$k=$v"
    }
    Set-Content -Path $Path -Value $lines -Encoding UTF8
}

# ---------- elevation ----------

function Test-Admin {
    $id = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $p  = New-Object System.Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-Admin {
    if (-not (Test-Admin)) {
        Write-Err "This script must be run as Administrator."
        Write-Sub "Right-click the script > 'Run with PowerShell as Administrator', or"
        Write-Sub "open an elevated PowerShell and re-run from there."
        exit 1
    }
}

# ---------- docker / compose helpers ----------

$Script:RepoRoot   = (Get-Item "$PSScriptRoot\..").FullName
$Script:DockerDir  = Join-Path $Script:RepoRoot 'docker'
$Script:ComposeBase = @('-f', (Join-Path $Script:DockerDir 'docker-compose.yml'))

function Get-ComposeArgs {
    param([switch]$WithGpu)
    $args = $Script:ComposeBase
    if ($WithGpu) { $args += @('-f', (Join-Path $Script:DockerDir 'compose.gpu.yml')) }
    $envFile = Join-Path $Script:RepoRoot '.env'
    if (Test-Path $envFile) { $args += @('--env-file', $envFile) }
    return $args
}

# ---------- waiting ----------

function Wait-HttpOk {
    param(
        [Parameter(Mandatory)][string]$Url,
        [int]$TimeoutSeconds = 90,
        [int]$IntervalSeconds = 3
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -SkipCertificateCheck -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) { return $true }
        } catch {
            # not yet ready — loop
        }
        Start-Sleep -Seconds $IntervalSeconds
    }
    return $false
}
```

- [ ] **Step 2: Create `scripts/install.ps1`**

```powershell
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
)

. "$PSScriptRoot\_common.ps1"

Write-Host @"

  ____  _                          _     
 |  _ \| |__   ___  _ __ ___  ___ (_)___ 
 | |_) | '_ \ / _ \| '__/ _ \/ __|| / __|
 |  __/| | | | (_) | | |  __/\__ \| \__ \
 |_|   |_| |_|\___/|_|  \___||___/|_|___/

  Standalone gel analyzer — installer

"@ -ForegroundColor Blue

# --- 0. Pre-flight ---
Assert-Admin

Write-Step "Verifying Windows 11"
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
    Write-Sub "Installing Docker Desktop via winget…"
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
    Write-Sub "Installing PostgreSQL 17 via winget…"
    winget install --silent --accept-package-agreements --accept-source-agreements PostgreSQL.PostgreSQL.17
    Write-Warn "Postgres installed. Set the 'postgres' user password during install if prompted."
    Write-Warn "Re-run this script after Postgres is configured."
    exit 0
}
Write-Ok "psql present ($(psql --version))"

# Create phoresis DB + user (idempotent — uses CREATE IF NOT EXISTS via DO blocks)
Write-Sub "Provisioning 'phoresis' database + user"
$pgPassword = Read-Host "Postgres superuser ('postgres') password" -AsSecureString
$pgPasswordPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pgPassword))

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
Write-Step "GPU variant"
$resolvedVariant = $Variant
if ($Variant -eq 'auto') {
    $nvSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($nvSmi) {
        try {
            $gpus = & nvidia-smi --query-gpu=name --format=csv,noheader 2>$null
            if ($LASTEXITCODE -eq 0 -and $gpus) {
                Write-Ok "NVIDIA GPU detected: $gpus"
                $resolvedVariant = 'cuda'
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

# --- 5. .env generation ---
Write-Step ".env"
$envPath = Join-Path $Script:RepoRoot '.env'
if (Test-Path $envPath) {
    Write-Sub ".env already exists — keeping it (delete to regenerate)"
} else {
    Write-Sub "Generating .env interactively"
    $adminEmail = Read-Host "Admin email"
    $adminPwd   = (Read-Host "Admin password" -AsSecureString | ConvertFrom-SecureString -AsPlainText)
    $userEmail  = Read-Host "Primary lab user email"
    $userPwd    = (Read-Host "Primary lab user password" -AsSecureString | ConvertFrom-SecureString -AsPlainText)
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
    Write-Warn "Could not auto-trust Caddy CA. The browser will show a security warning the first time — accept it manually."
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
$lnk.Description = "Phoresis — Gel Electrophoresis Analyzer"
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
```

- [ ] **Step 3: Commit**

```bash
git add scripts/_common.ps1 scripts/install.ps1
git commit -m "feat(scripts): add install.ps1 (clean-machine) + _common.ps1 helpers"
```

---

## Task 5: `start.ps1` and `stop.ps1`

**Files:**
- Create: `scripts/start.ps1`
- Create: `scripts/stop.ps1`

- [ ] **Step 1: Create `scripts/start.ps1`**

```powershell
<#
.SYNOPSIS
    Start the Phoresis stack and open the browser.

.DESCRIPTION
    Wired to the desktop shortcut. Idempotent — can be run while the stack
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
```

- [ ] **Step 2: Create `scripts/stop.ps1`**

```powershell
<#
.SYNOPSIS
    Stop the Phoresis stack. Volumes are preserved.

.DESCRIPTION
    `docker compose down` only — does NOT pass -v, so phoresis_staticfiles,
    phoresis_media, phoresis_redis, caddy_data, caddy_config all survive.
    To wipe everything (DEV ONLY), pass -Wipe.
#>
[CmdletBinding()]
param(
    [switch]$Wipe
)

. "$PSScriptRoot\_common.ps1"

$envMap = Read-EnvFile (Join-Path $Script:RepoRoot '.env')
$variant = $envMap['PHORESIS_IMAGE_VARIANT']
if (-not $variant) { $variant = 'cpu' }

$composeArgs = Get-ComposeArgs -WithGpu:($variant -eq 'cuda')

if ($Wipe) {
    Write-Warn "WIPE MODE — this will delete static, media, redis, and caddy volumes."
    Write-Warn "Postgres data on the HOST is unaffected (always)."
    $confirm = Read-Host "Type 'WIPE' to confirm"
    if ($confirm -ne 'WIPE') {
        Write-Err "Aborted."
        exit 1
    }
    Write-Step "docker compose down -v"
    & docker compose @composeArgs down -v
} else {
    Write-Step "docker compose down (volumes preserved)"
    & docker compose @composeArgs down
}

if ($LASTEXITCODE -eq 0) {
    Write-Ok "Phoresis stopped."
} else {
    Write-Err "docker compose down failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}
```

- [ ] **Step 3: Commit**

```bash
git add scripts/start.ps1 scripts/stop.ps1
git commit -m "feat(scripts): add start.ps1 + stop.ps1 (daily lifecycle)"
```

---

## Task 6: `update.ps1` — manual update + `-Rollback`

**Files:**
- Create: `scripts/update.ps1`

- [ ] **Step 1: Create `scripts/update.ps1`**

```powershell
<#
.SYNOPSIS
    Update Phoresis to the newest tagged release (or roll back to a specific tag).

.PARAMETER Rollback
    Pin the stack to a specific version tag (e.g. v0.4.0). Disables Watchtower
    auto-update by writing PHORESIS_IMAGE_TAG to .env, which the compose file
    consults via ${PHORESIS_IMAGE_TAG:-latest-${variant}}.

.EXAMPLE
    .\scripts\update.ps1                    # pull latest, restart
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

Write-Step "docker compose pull"
& docker compose @composeArgs pull
if ($LASTEXITCODE -ne 0) {
    Write-Err "Pull failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
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
```

> **Note on Watchtower interaction:** When a rollback pins `PHORESIS_IMAGE_TAG=vX.Y.Z`, the compose file's `${PHORESIS_WEB_IMAGE:-...}` resolves to a specific tag (not `:latest-{variant}`), and Watchtower won't pull anything because the tag is fixed. Running `update.ps1` without `-Rollback` clears the pin and resumes auto-updates.

- [ ] **Step 2: Verify the compose file actually consults `PHORESIS_WEB_IMAGE`**

Re-check `docker/docker-compose.yml` from Phase 5 — the `image:` line for `web` should be:
```yaml
    image: ${PHORESIS_WEB_IMAGE:-ghcr.io/gmathy2104/phoresis-web:latest-${PHORESIS_IMAGE_VARIANT:-cpu}}
```
This was already the pattern in Phase 5 Task 7. ✓

- [ ] **Step 3: Commit**

```bash
git add scripts/update.ps1
git commit -m "feat(scripts): add update.ps1 with -Rollback flag (pins PHORESIS_IMAGE_TAG)"
```

---

## Task 7: `backup.ps1` and `restore.ps1`

**Files:**
- Create: `scripts/backup.ps1`
- Create: `scripts/restore.ps1`

Backup target: `%USERPROFILE%\Phoresis-Backups\YYYY-MM-DD_HHmmss\`
Contents per backup:
- `db.sql.gz` (compressed pg_dump of `phoresis`)
- `media.tar.gz` (tar of `phoresis_media` Docker volume)
- `meta.json` (timestamp, version, image variant)

Retention: 30 days (older directories deleted on each run). Schedulable via Windows Task Scheduler.

- [ ] **Step 1: Create `scripts/backup.ps1`**

```powershell
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
$composeArgs = Get-ComposeArgs

# Run a tar inside an alpine container with the volume mounted
& docker run --rm `
    -v phoresis_phoresis_media:/data:ro `
    -v "$snapshotDir:/backup" `
    alpine:3 sh -c "cd /data && tar czf /backup/media.tar.gz ."
if ($LASTEXITCODE -ne 0) {
    Write-Warn "media tar failed (exit $LASTEXITCODE) — DB backup is preserved"
} else {
    Write-Ok "Media tar: $((Get-Item $mediaTar).Length / 1MB | ForEach-Object { '{0:F2} MB' -f $_ })"
}

# --- 3. Metadata ---
$meta = @{
    timestamp = $timestamp
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
```

- [ ] **Step 2: Create `scripts/restore.ps1`**

```powershell
<#
.SYNOPSIS
    Restore Phoresis from a backup snapshot — interactive selection.

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
    Write-Warn "The Phoresis stack is still running. Stopping it first…"
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
    & docker run --rm `
        -v phoresis_phoresis_media:/data `
        -v "$($picked.FullName):/backup:ro" `
        alpine:3 sh -c "cd /data && rm -rf ./* && tar xzf /backup/media.tar.gz"
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "media restore failed (exit $LASTEXITCODE) — DB is restored"
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
```

- [ ] **Step 3: Document the Task Scheduler integration**

Append to `CONTRIBUTING.md` (or `docs/INSTALL.md` if it exists by Phase 7):

```markdown
## Scheduled backups

To run `backup.ps1` daily at 02:30:

```powershell
# Run as Administrator
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -File `"$PWD\scripts\backup.ps1`""
$trigger = New-ScheduledTaskTrigger -Daily -At 2:30AM
Register-ScheduledTask -TaskName "Phoresis Daily Backup" `
    -Action $action -Trigger $trigger -RunLevel Highest
```
```

- [ ] **Step 4: Commit**

```bash
git add scripts/backup.ps1 scripts/restore.ps1 CONTRIBUTING.md
git commit -m "feat(scripts): add backup.ps1 + restore.ps1 (pg_dump + media tar, 30-day retention)"
```

---

## Task 8: Watchtower credentials story (public images)

**Files:**
- Modify: `docker/docker-compose.yml` (no functional change — comments only)
- Modify: `CONTRIBUTING.md` (private-image fallback)

The decision lands here: **Phoresis images are PUBLIC on GHCR.** This means:

1. `install.ps1` does NOT need `docker login ghcr.io`.
2. Watchtower polls without credentials.
3. Anyone can `docker pull ghcr.io/gmathy2104/phoresis-web:latest-cpu` and inspect the image.

If a future operator wants private images, they:

1. Switch the GHCR package visibility to private via the GitHub UI.
2. Add a Personal Access Token to their Phoresis machine via `docker login ghcr.io`.
3. Set `WATCHTOWER_AUTH_USERNAME` + `WATCHTOWER_AUTH_PASSWORD` (or use a Docker config volume mount) in the compose file.

- [ ] **Step 1: Add a comment block to `docker/docker-compose.yml`** documenting the public-default

Find the `web:` service block and prepend a comment:

```yaml
  # ────────────────────── Django web ──────────────────────
  # Default: public GHCR image (no docker login required).
  # For private-image deployments:
  #   1. Set the GHCR package visibility to Private in GitHub Packages.
  #   2. On every Phoresis machine, run: docker login ghcr.io -u <gh-user> -p <PAT>
  #      where <PAT> has read:packages scope only.
  #   3. Add WATCHTOWER_AUTH_USERNAME + WATCHTOWER_AUTH_PASSWORD env vars to the
  #      watchtower service below (or mount ~/.docker/config.json read-only).
  web:
```

- [ ] **Step 2: Append the same note to `CONTRIBUTING.md`**

```markdown
## Image visibility (public/private)

Phoresis images on `ghcr.io/gmathy2104/phoresis-{web,worker}` are PUBLIC by
default. The image content is open-source code + open-weights ML models —
no secrets, no proprietary data. Public eliminates `docker login` friction
in `install.ps1`.

To switch to private images:

1. Make the GHCR package private (GitHub UI → Packages → Settings).
2. On each Phoresis host, run `docker login ghcr.io` once (with a PAT that
   has `read:packages`).
3. Add Watchtower auth env vars in `docker/docker-compose.yml`:
   ```yaml
   watchtower:
     environment:
       WATCHTOWER_AUTH_USERNAME: <gh-user>
       WATCHTOWER_AUTH_PASSWORD: ${GHCR_PAT}
   ```
   (and add `GHCR_PAT=...` to `.env`).
```

- [ ] **Step 3: Commit**

```bash
git add docker/docker-compose.yml CONTRIBUTING.md
git commit -m "docs: document Phoresis public-image default + private-fallback for GHCR"
```

---

## Task 9: Clean-machine validation walk-through

This task is a **playbook**, not new code. It validates that the install pipeline works end-to-end on a fresh box. The agent walks through it manually (or on a VM snapshot) and reports back.

- [ ] **Step 1: Set up a clean Windows 11 VM**

Either:
- A fresh Hyper-V / VirtualBox / VMware Workstation Windows 11 install, OR
- A Windows Sandbox session (`WindowsSandbox.exe`), OR
- A snapshot of a clean Windows 11 image rolled back before each attempt.

Make sure the VM has:
- ≥ 16 GB RAM (Docker Desktop minimum + Postgres + the stack).
- ≥ 60 GB free disk.
- Internet access (winget, Docker Hub, GHCR).
- (Optional) NVIDIA GPU passthrough if validating CUDA.

- [ ] **Step 2: Clone the repo**

```powershell
git clone https://github.com/gmathy2104/phoresis.git
cd phoresis
git lfs pull
```

- [ ] **Step 3: Run `install.ps1`**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

Expected timeline (rough):
- Pre-flight + GPU detection: < 30s
- Docker Desktop install (if missing): 3-5 min (one reboot/sign-out interruption)
- Postgres install: 2-3 min
- Hosts entry + .env generation: < 1 min
- `docker compose pull`: 5-10 min on first run (downloads ~2 GB CPU image or ~5 GB CUDA)
- `docker compose up -d` + healthcheck: 30-60s
- Browser open: instant

Total: 10-20 min on cold cache, < 5 min on warm.

Expected end state:
- `https://phoresis/` opens to the login page.
- Sign in with the primary user credentials → land on dashboard.
- Sidebar links work.
- `start.ps1` desktop shortcut exists with the Phoresis icon.

- [ ] **Step 4: Run each daily script**

```powershell
.\scripts\stop.ps1
.\scripts\start.ps1     # should bring it back up
.\scripts\update.ps1    # should pull (no-op on freshly-pulled images)
.\scripts\backup.ps1    # creates a snapshot in %USERPROFILE%\Phoresis-Backups
.\scripts\restore.ps1   # interactive — pick the snapshot we just made
```

Each should report success without errors.

- [ ] **Step 5: Document any rough edges**

Take notes during the walk-through. Anything that surprised you, asked for input twice, or required a workaround → file an issue or fix inline.

Common issues observed during a typical first run:
- Docker Desktop install requires a sign-out/sign-in cycle for WSL2 integration → script exits early; user reruns it. This is documented behaviour; don't try to bypass.
- Caddy CA trust requires admin (script checks).
- Postgres password during winget install isn't auto-set — user is prompted.

- [ ] **Step 6: Commit any fixes from the walk-through**

```bash
git status
```
If anything changed:
```bash
git add -u
git commit -m "fix(scripts): rough-edge fixes from clean-machine validation"
```

---

## Task 10: Final pass + tag v0.6.0

- [ ] **Step 1: Run the full local test suite**

```bash
.venv/Scripts/python.exe -m pytest -v
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m pre_commit run --all-files
```
Expected: all green. Phase 6 doesn't add Python tests, so the count stays at ~285.

- [ ] **Step 2: Verify the release dry-run works**

The release pipeline can't actually run until pushed to GitHub, but we can verify the YAML syntax + the matrix expansion:

```bash
actionlint .github/workflows/ci.yml .github/workflows/release.yml 2>&1 || true
```

Manually inspect `.github/workflows/release.yml` and confirm:
- The matrix produces 4 jobs: `web-cpu`, `web-cuda`, `worker-cpu`, `worker-cuda`.
- Each pushes to two tags: `:vX.Y.Z-{variant}` and `:latest-{variant}`.
- The `release-please` job is gated on `push` to `main`.
- The `attach-assets` job depends on `build-and-push` and only runs on tag pushes.

- [ ] **Step 3: Inspect script syntax**

```bash
powershell -Command "& {
  Get-ChildItem scripts/*.ps1 | ForEach-Object {
    \$null = [System.Management.Automation.PSParser]::Tokenize((Get-Content \$_.FullName -Raw), [ref]\$null)
    Write-Host \"\$(\$_.Name): OK\"
  }
}"
```
Expected: each `.ps1` file prints `OK`. PSParser fails on syntax errors.

- [ ] **Step 4: Tag v0.6.0**

```bash
git tag -a v0.6.0 -m "Phase 6: CI/CD + install scripts — release-please, ci.yml extended (e2e + Trivy), release.yml (matrix build + GHCR push), 6 PowerShell scripts (install/start/stop/update/backup/restore)"
git tag --list
```

- [ ] **Step 5: When pushed to GitHub, verify the workflows actually run**

Outside the worktree-local validation, when this lands on `main`:
- `ci.yml` should run on the PR + on push to `main`.
- `release.yml`'s `release-please` job opens a "chore(main): release 0.7.0" PR (since v0.6.0 is now in the manifest).
- Merging that PR tags `v0.7.0` and triggers the build matrix.

For Phase 6 acceptance, just confirming the YAML is valid + first-PR-to-main triggers `ci.yml` is enough. The actual release on tag push is a Phase 7 concern (the v1.0.0 release).

---

## Acceptance criteria for Phase 6

This phase is **done** when ALL of the following hold:

1. `.github/workflows/ci.yml` runs to green on every PR: lint + frontend build + tests + e2e + Docker image build + Trivy scan. No CRITICAL or HIGH unfixed CVEs (Trivy `exit-code: 1` on those).
2. `.github/workflows/release.yml` syntax-validates and produces 4 matrix jobs when triggered.
3. `release-please` config + manifest exist and target `pyproject.toml`'s `[project].version`.
4. `CHANGELOG.md` exists and is auto-managed.
5. `scripts/install.ps1` brings a clean Windows 11 box from "nothing" to `https://phoresis/` open in the browser, idempotent on re-runs.
6. `scripts/start.ps1`, `stop.ps1`, `update.ps1` (with `-Rollback`), `backup.ps1`, `restore.ps1` all run without errors and surface meaningful output.
7. `update.ps1 -Rollback v0.5.0` pins the stack to v0.5.0 images; subsequent `update.ps1` (no flag) clears the pin.
8. `backup.ps1` creates a `db.sql.gz` + `media.tar.gz` + `meta.json` triple under `%USERPROFILE%\Phoresis-Backups\YYYY-MM-DD_HHmmss\`. `restore.ps1` reverses it.
9. Watchtower configuration documented for both public (default) and private GHCR cases.
10. The git tag `v0.6.0` exists.
11. `pytest -v`, `ruff check .`, `ruff format --check .`, `pre-commit run --all-files` are green.
12. Spec §9.4 / §10.1 invariants:
    - 6 PowerShell scripts, all idempotent.
    - Matrix `(cpu, cuda) × (web, worker) = 4` image builds in `release.yml`.
    - GHCR tags follow `:vX.Y.Z-{variant}` + `:latest-{variant}`.
    - Trivy scan with CRITICAL/HIGH unfixed-block and `exit-code: 1` blocks releases (per spec §11.5 "CRITICAL vulnerabilities block release").
13. Spec §13 "image visibility" decision documented: PUBLIC by default; private fallback in 3 steps.
