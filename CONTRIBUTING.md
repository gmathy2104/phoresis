# Contributing to Phoresis

## Tests

Run the full suite with:

```bash
.venv/Scripts/python.exe -m pytest -v
```

### Speed-up: `--reuse-db`

For long-running suites, you can opt into reusing the test database between runs:

```bash
.venv/Scripts/python.exe -m pytest -v --reuse-db
```

This skips schema migration on subsequent runs. **Caveat:** if you've added a new migration, you must use `--create-db` once to refresh the schema:

```bash
.venv/Scripts/python.exe -m pytest -v --create-db
```

We don't enable `--reuse-db` by default in `pyproject.toml` because it's a frequent source of stale-schema test failures during phases of rapid migration churn.

## Release flow

1. Land changes on `main` using [Conventional Commits](https://www.conventionalcommits.org/):
   - `feat: ...` → minor version bump
   - `fix: ...` → patch bump
   - `feat!: ...` or `BREAKING CHANGE:` in body → major bump
2. `release-please` opens a PR titled "chore(main): release X.Y.Z" with the bumped version + auto-generated CHANGELOG entries.
3. Review and merge the PR.
4. Merging tags `vX.Y.Z` and triggers `release.yml`, which:
   - Builds **one** unified image (CPU only — CUDA users build locally).
   - Pushes to `ghcr.io/gmathy2104/phoresis-app:{vX.Y.Z, latest}-cpu`.
   - Creates a GitHub Release with auto-generated notes.
   - Attaches the SBOM.
5. Watchtower (running on every Phoresis install) detects the new `:latest-{variant}` digest at 03:00 daily and self-updates the web/worker/scheduler containers (all three run the same image).

## Manual rollback

Pin a specific image tag in `.env`:

```
PHORESIS_IMAGE_TAG=v0.4.0-cpu
```

Then run `scripts/update.ps1 -Rollback v0.4.0`.

## Scheduled backups

To run `backup.ps1` daily at 02:30 (run as Administrator):

```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -File `"$PWD\scripts\backup.ps1`""
$trigger = New-ScheduledTaskTrigger -Daily -At 2:30AM
Register-ScheduledTask -TaskName "Phoresis Daily Backup" `
    -Action $action -Trigger $trigger -RunLevel Highest
```

## Storage paths

User data lives at host paths, not in Docker named volumes:

| Data | Default host path | Override |
|---|---|---|
| Database | Native PostgreSQL on Windows host (port 5432) | `DB_HOST` / `DB_PORT` in `.env` |
| Media (gel images, thumbnails, exports) | `%USERPROFILE%\Phoresis-Data\media` | `PHORESIS_MEDIA_DIR` in `.env`, set by `install.ps1 -DataDir <path>` |
| Backups | `%USERPROFILE%\Phoresis-Backups\YYYY-MM-DD_HHmmss\` | `backup.ps1 -OutDir <path>` |

Static files, Caddy TLS state, and Redis broker state live in **Docker named volumes**
(`phoresis_staticfiles`, `caddy_data`, `caddy_config`, `phoresis_redis`) because they're
regenerable: `collectstatic` rebuilds static files on every container start, Caddy
re-issues its self-signed cert if `caddy_data` is wiped, and Redis only holds in-flight
Celery task state.

This means **`docker compose down -v` cannot wipe user data** — it only blasts the four
disposable volumes. Database stays on the host, media stays at `PHORESIS_MEDIA_DIR`.

## Documentation

When you add or change a feature, update the relevant doc:

- New templatetag → [docs/DESIGN.md](docs/DESIGN.md) component catalogue + [src/phoresis_ui/docs/README.md](src/phoresis_ui/docs/README.md).
- New service in `gel_analyzer` → [src/gel_analyzer/docs/README.md](src/gel_analyzer/docs/README.md).
- New PowerShell script → [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) and (if user-facing) [docs/INSTALL.md](docs/INSTALL.md).
- New Celery task → [src/gel_analyzer/docs/README.md](src/gel_analyzer/docs/README.md), and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) if it changes the data flow.
- Architectural decision → write a short ADR under `docs/adr/` (template the directory if it doesn't exist yet).

The [README.md](README.md) cross-links to all the above; keep its "Documentation" section current too.

## Image visibility (public/private)

The Phoresis image on `ghcr.io/gmathy2104/phoresis-app` is PUBLIC by
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
