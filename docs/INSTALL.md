# Installing Phoresis

This is the end-user walkthrough. Follow it once on a fresh laptop and you'll have Phoresis running at `https://phoresis/` with Postgres on the host, Docker handling everything else, and a desktop shortcut to start it. The whole thing takes about 15 minutes — most of which is unattended download time.

If you're a developer cloning the repo, read [DEVELOPMENT.md](DEVELOPMENT.md) instead.

![Phoresis dashboard](images/hero-dashboard.png)

*The Phoresis dashboard after first sign-in. KPI cards count up from 0; recent gels populate as you upload.*

Phoresis is a single-user gel electrophoresis analyzer for the laptop on your bench. You upload a gel image, it auto-extracts lanes, you (or it) draw bands, and it gives you molecular weights, intensity, and side-by-side comparisons. Everything lives on your machine — there is no cloud, no account to create, no data leaving your computer.

## 1. Prerequisites

- **Windows 10 (build 19045+) or Windows 11.** Tested on Windows 11 Pro 23H2 and 24H2.
- **At least 16 GB RAM** — 8 GB is the documented floor but band detection on a 12-lane gel is uncomfortable below 16.
- **At least 60 GB free disk** — the install + a few months of gels.
- **Internet access** for the first install (to pull Docker images and PostgreSQL). After that the app runs offline.
- **(Optional) NVIDIA GPU** — speeds up hybrid band detection. If you have one and you've installed the NVIDIA drivers, the installer will offer the CUDA image variant.
- **Administrator rights** on the laptop for the install step. Day-to-day use does not require admin.

## 2. Step 1 — Download

Either clone with git:

```powershell
git clone https://github.com/gmathy2104/phoresis.git
cd phoresis
git lfs pull
```

…or download the latest `phoresis-vX.Y.Z.zip` from the [Releases page](https://github.com/gmathy2104/phoresis/releases) and unzip it into `C:\Phoresis\` (or anywhere you like — keep it short, no spaces).

Either way, you should now have a `phoresis\` folder with a `scripts\` subfolder inside it.

## 3. Step 2 — Run the installer (admin)

Right-click `scripts\install.ps1` → **Run with PowerShell as Administrator**. (PowerShell will prompt for the elevation; click yes.)

![PowerShell elevation prompt + first lines of install.ps1 output](images/install-step-1.png)

*The installer announces what it will do, then asks before each step.*

The installer:

1. Checks for Docker Desktop — if missing, installs it via `winget install Docker.DockerDesktop`.
2. Checks for PostgreSQL 17 — if missing, installs it via `winget install PostgreSQL.PostgreSQL.17` and prompts for the postgres password.
3. Generates `.env` interactively (admin email + password, lab-user email + password, image variant, media directory).
4. Imports the Caddy self-signed root CA into the Windows trust store.
5. Pulls `ghcr.io/gmathy2104/phoresis:latest-${variant}` and starts the stack.
6. Creates a Windows desktop shortcut to `scripts\start.ps1`.

## 4. Step 3 — Docker Desktop install (if first run)

If the installer had to install Docker Desktop, **Windows will sign you out** to enable WSL2 / Hyper-V. This is normal. Sign back in, open Docker Desktop once and accept the EULA, then re-run `scripts\install.ps1` from the same folder. It will pick up where it left off.

## 5. Step 4 — Postgres password

If the installer had to install PostgreSQL, `winget` will prompt for the postgres superuser password during the install. Pick something you'll remember — the installer will ask for it again a few seconds later when it creates the `phoresis` database and user.

(If PostgreSQL was already installed, the installer just asks for the existing postgres password.)

## 6. Step 5 — `.env` prompts

After Docker and Postgres are confirmed, the installer walks you through the `.env` file:

![the interactive .env prompt screen](images/install-step-2.png)

*The .env builder, one prompt at a time. Defaults are in square brackets; press Enter to accept.*

You will be asked for:

- **Admin email + password** — the Django superuser, used for `/admin/` only. Store this somewhere safe; it's not recoverable without database access.
- **Lab user email + password** — the day-to-day account you'll sign in with from the browser.
- **Image variant** — `cpu` (default) or `cuda` if you have an NVIDIA GPU.
- **Media directory** — default `./_phoresis_data/media` under the install folder; pick a different drive if you expect lots of gels.

The `.env` file is written, gitignored, and never printed to stdout.

## 7. Step 6 — First boot

The installer pulls the Docker images (`phoresis`, `caddy`, `redis`, `watchtower`), starts the stack, and waits for `/healthz/` to return 200. The first pull is the longest part — about 5 minutes on a typical lab connection. When the stack is healthy, the installer opens `https://phoresis/` in your default browser.

![desktop shortcut + browser at https://phoresis/](images/install-step-3.png)

*A "Phoresis" desktop shortcut is created; the browser opens to the sign-in page.*

If the browser shows a certificate warning, the trust-store import in step 3 didn't finish. Re-run `scripts\install.ps1` (it's idempotent) — the Import-Certificate step will retry.

## 8. Step 7 — Sign in

Use the **lab user** credentials from step 6 (not the admin credentials — those are for `/admin/` only). After sign-in you land on the dashboard, with empty KPI cards and an "Upload your first gel" empty state.

## 9. Step 8 — Daily use

Double-click the **Phoresis** desktop shortcut (which runs `scripts\start.ps1`). The script ensures Docker Desktop is running, brings the stack up if it isn't, and opens the browser. Closing the browser does **not** stop the stack — Phoresis keeps running in the background so band detection finishes even if you walk away.

To explicitly stop the stack: right-click the desktop shortcut → **Stop**, or run `scripts\stop.ps1`. To wipe regenerable Docker volumes (Caddy state, Redis AOF, staticfiles) without touching your gels: `scripts\stop.ps1 -Wipe`. **`-Wipe` cannot delete user data** — your database is on the host and your media is in a host bind-mount.

## 10. Annotate, analyze, compare

Once you have a gel uploaded, the workflow is:

![annotation editor with a gel image + lanes drawn](images/annotate-viewer.png)

*The annotation editor. Drag to define lanes; click to drop bands; the right panel shows the live measurement table.*

![densitometry view with electropherogram](images/densitometry-view.png)

*Densitometry: the electropherogram is generated from the lane column profile, with peaks called and assigned to bands.*

![4-panel comparison view](images/comparison-view.png)

*Comparison view: four lanes (or four whole gels) side-by-side, with synchronized panning and a shared MW axis.*

The theme toggle is in the topbar, top-right:

![the topbar with the theme switcher highlighted](images/theme-toggle.png)

*Light / Dark / System; choice is persisted server-side, so it follows you across devices.*

## 11. Backup setup

Phoresis ships with `scripts\backup.ps1`, which dumps Postgres + the media folder + `.env` into a timestamped folder under `%USERPROFILE%\Phoresis-Backups\`. To run it nightly via Task Scheduler:

1. Open **Task Scheduler** → **Create Task…**.
2. Name: `Phoresis nightly backup`. Trigger: daily at 02:30 (before Watchtower's 03:00 update poll).
3. Action: **Start a program** → `powershell.exe`. Arguments: `-NoProfile -ExecutionPolicy Bypass -File "C:\Phoresis\scripts\backup.ps1"` (adjust the path to your install).
4. Run whether user is logged on or not, with highest privileges.

Test by running the task manually once. The first run takes a minute or two; subsequent runs are incremental on the media folder.

## 12. Updating

You don't need to do anything. Watchtower polls `ghcr.io` every day at 03:00 and pulls new versions of the `web`, `worker`, and `scheduler` containers in place. Caddy and Redis are deliberately excluded — they only update when you run the manual update script.

To update everything (Caddy + Redis included) on demand: `scripts\update.ps1`.

To pin to a specific older version (e.g. after a regression): `scripts\update.ps1 -Rollback v1.2.3`. See [DEPLOYMENT.md §6](DEPLOYMENT.md#6-rollback) for details.

## 13. If something breaks

Every internal error renders a branded 500 page with a `PHOR-XXXXX` reference ID. **Write that ID down before clicking away.** With it, support (or you, in the admin) can find the exact stack trace under `/admin/phoresis_core/errorlog/`.

The first place to check when the browser shows nothing or a 502:

```powershell
docker compose ps             # what is running
docker compose logs -f web    # live tail of the Django container
```

For the common failure modes (cert warning, healthz failures, Watchtower errors) see the [DEPLOYMENT.md troubleshooting table](DEPLOYMENT.md#10-common-troubleshooting).

## 14. Uninstall

To stop the stack and wipe regenerable Docker volumes (your gels are safe — they live on the host):

```powershell
.\scripts\stop.ps1 -Wipe
```

To remove Docker Desktop and PostgreSQL from the laptop entirely (this **does** wipe the database):

```powershell
winget uninstall Docker.DockerDesktop
winget uninstall PostgreSQL.PostgreSQL.17
```

Finally delete the `phoresis\` folder. The desktop shortcut is removed automatically when its target disappears.

---

> **Screenshots:** Captured during Phase 7 Task 10 hands-on validation. If any reference is missing, the install path still works — the markdown image will simply not render.
