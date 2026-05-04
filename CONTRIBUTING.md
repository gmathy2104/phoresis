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

## Scheduled backups

To run `backup.ps1` daily at 02:30 (run as Administrator):

```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -File `"$PWD\scripts\backup.ps1`""
$trigger = New-ScheduledTaskTrigger -Daily -At 2:30AM
Register-ScheduledTask -TaskName "Phoresis Daily Backup" `
    -Action $action -Trigger $trigger -RunLevel Highest
```

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
