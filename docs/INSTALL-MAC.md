# Phoresis on a Mac (Apple Silicon)

How to run Phoresis on a Mac mini (or any Apple Silicon Mac) that stays on, next to other
self-hosted apps such as CamHub. The Windows install ([INSTALL.md](INSTALL.md)) is unchanged: the two
are independent ways to run the same code.

## What is different from Windows

| | Windows | Mac |
|---|---|---|
| Processes | six Docker containers | native processes, no Docker |
| Kept alive by | Docker `restart: unless-stopped` | launchd (`local.phoresis.*` LaunchAgents) |
| PostgreSQL | native, on the host | native (Homebrew), database `phoresis` in the shared server |
| Redis | a container | native, an instance of its own (`127.0.0.1:6390`, password) |
| HTTPS | Caddy container, `https://phoresis` | Caddy, `https://phoresis.local` (port 8443 if 443 is taken) |
| Media | Docker volume `phoresis_phoresis_media` | a folder on the Mac, plus an optional archive on an external disk |
| Updates | Watchtower, nightly | `phoresis.sh update` (nightly on request) |
| Backups | `scripts/backup.ps1` | nightly, automatic |

Why native: a container on a Mac runs inside a Linux virtual machine, which costs memory, cannot use
the Mac's GPU, and adds a file-sharing layer between the app and its disks. Natively, Python and its
numeric libraries are Apple Silicon builds, PyTorch can use the GPU (MPS), and the app reads its disks
directly. One entry point does everything: `scripts/mac/phoresis.sh`.

## Living next to CamHub

Nothing is shared except the PostgreSQL server, where each app has its own database and role.

| | CamHub | Phoresis |
|---|---|---|
| launchd label | `local.camhub.hub` | `local.phoresis.{redis,web,worker,beat,caddy,mdns,nightly}` |
| HTTPS | 443 (`camhub.local`) | 8443 (`phoresis.local`), or 443 on a Mac without CamHub |
| Django | 127.0.0.1:8000 | 127.0.0.1:8710 |
| Redis | Homebrew service, 6379 | its own, 6390 |
| Database | `camhub` | `phoresis` |
| Data | `var/` in its checkout | `~/Library/Application Support/Phoresis` |

`install` picks free ports itself and writes them to `.env`. Both apps answering on port 443 would
need one of the two Caddy servers to front the other: not done, and not needed.

## Install

Clone outside Documents, Desktop and Downloads (macOS keeps background services out of them), for
example in `~/phoresis`:

```bash
git clone https://github.com/gmathy2104/phoresis.git ~/phoresis
```

```bash
~/phoresis/scripts/mac/phoresis.sh install
```

It asks for the admin and lab accounts once, then:

1. installs what is missing with Homebrew (`uv`, `caddy`, `redis`, `node`, `git-lfs`, PostgreSQL),
   after asking;
2. fetches the ML models from Git LFS;
3. writes `.env` (secrets generated, ports chosen, mode 600);
4. creates the `phoresis` role and database in the local PostgreSQL;
5. builds the Python environment (Python 3.12, managed by uv) and the stylesheet;
6. migrates, collects static files, seeds groups, ladders and the two accounts;
7. installs and starts the seven LaunchAgents.

Then open the address it prints, `https://phoresis.local:8443` on a Mac that also runs CamHub.
Re-running `install` is safe: it keeps `.env` and only completes it.

### Trust the certificate (once)

Caddy signs the site's certificate with a local authority of its own. Browsers warn until that
authority is trusted:

```bash
~/phoresis/scripts/mac/phoresis.sh trust
```

prints the `sudo security add-trusted-cert ...` command to run on the Mac, and the path of the
`root.crt` to copy to other computers.

### A Mac mini that restarts on its own

LaunchAgents start when the user session opens. For Phoresis to come back after a power cut without
anyone at the keyboard: enable automatic login (System Settings > Users & Groups) and "Start up
automatically after a power failure" (System Settings > Energy). While Phoresis runs, the Mac does
not go to sleep (`caffeinate`, effective on mains power).

## Sign-in security

- **Two-factor is required for the admin account** (`PHORESIS_REQUIRE_2FA=staff` in `.env`). At the
  first sign-in the admin scans a QR code with an authenticator app, then keeps the 10 backup codes
  shown once. Other accounts can turn it on from their profile; `all` in `.env` requires it for
  everyone, `off` for no one (then `restart`).
- **Five wrong passwords** pause that account from that device for 15 minutes.
- **Phone and backup codes lost:** `scripts/mac/phoresis.sh manage reset_two_factor <email>`.
  **Locked out:** `scripts/mac/phoresis.sh manage axes_reset_username <username>`.
- **Reaching the Mac from outside the house:** open no port on the router. Use a VPN (Tailscale or
  WireGuard) so that Phoresis stays reachable only from your own devices. `phoresis.local` does not
  resolve through a VPN: the Mac's VPN name has to be added to `DJANGO_ALLOWED_HOSTS`,
  `DJANGO_CSRF_TRUSTED_ORIGINS` and the Caddy site, which the install script does not do yet.
- Gel images under `/media/` are served without a session to whoever can reach the server and knows
  the file's URL: one more reason to keep the server off the open internet.

## Daily commands

```
scripts/mac/phoresis.sh status         services, URL, sleep, storage, last backup
scripts/mac/phoresis.sh restart        restart everything, migrations included
scripts/mac/phoresis.sh stop | start
scripts/mac/phoresis.sh update         git pull, rebuild, migrate, restart   (--release: latest tag)
scripts/mac/phoresis.sh logs [web|worker|beat|caddy|redis|mdns|nightly]
scripts/mac/phoresis.sh backup         now
scripts/mac/phoresis.sh restore DIR    a dated folder from the backups
scripts/mac/phoresis.sh storage status | archive | restore | verify
scripts/mac/phoresis.sh manage ...     any manage.py command
scripts/mac/phoresis.sh uninstall      removes the services; data, database and .env stay
```

A service that stops is restarted by launchd. An automatic restart never migrates the database:
only `install`, `restart` and `update` do.

## Storage: the Mac's disk and an external disk

Gel originals are large and are kept for years; the Mac's internal disk is small and shared. Phoresis
therefore uses two places:

- **This Mac** (`~/Library/Application Support/Phoresis/media`): every upload lands here. Display
  images and thumbnails always stay here.
- **The archive disk** (a folder on an external drive): where the *oldest originals* move when gels
  take more than their quota on the Mac.

Set it up once, with the disk plugged in:

```bash
~/phoresis/scripts/mac/phoresis.sh archive-disk "/Volumes/<disk>/Phoresis/media"
```

```bash
~/phoresis/scripts/mac/phoresis.sh disk-access
```

The second command explains the one macOS permission needed: a background service may not read an
external disk until its program has **Full Disk Access**. Phoresis is built so that a single program
needs it, its Python interpreter. Without it the app keeps working, reports the archive as
unavailable, and archives nothing.

What happens then:

- Every night at 04:15, if gels use more than `PHORESIS_MEDIA_HOT_QUOTA_GB` (50) on the Mac, or the
  Mac's disk has less than `PHORESIS_MEDIA_MIN_FREE_GB` (20) free, the oldest originals (older than
  `PHORESIS_MEDIA_ARCHIVE_MIN_AGE_DAYS`, 30) are moved until usage is 10 % under the quota.
- A file is copied, flushed to the disk, re-read and compared before the Mac's copy is deleted.
- Nothing changes in the app: an archived gel opens as before, a little slower.
- **Disk unplugged**: gels still list and display; re-processing an archived gel says to reconnect
  the disk; nothing is ever written to the Mac in the disk's place; archiving resumes when the disk
  is back. The dashboard shows a "Media storage" card to staff, with a warning in that case.
- The archive stops before filling the external disk (`PHORESIS_MEDIA_ARCHIVE_MIN_FREE_GB`, 5).

```
scripts/mac/phoresis.sh storage status           both disks, quota, what is archived
scripts/mac/phoresis.sh storage archive --dry-run
scripts/mac/phoresis.sh storage archive --gb 20   move 20 GB now, whatever the quota
scripts/mac/phoresis.sh storage restore --all     bring everything back to the Mac
scripts/mac/phoresis.sh storage verify --deep     re-read every archived file against its checksum
```

**An archived original exists only on the archive disk.** The archive frees space; it is not a
backup. Back that disk up (Time Machine can include it, or a second disk), and run `storage verify`
from time to time.

## Backups

Every night at 02:30 (`local.phoresis.nightly`), and on demand with `backup`:

- a `pg_dump` of the database into a dated folder, the last `PHORESIS_BACKUP_KEEP` (14) kept;
- a mirror of the media that are on the Mac, when the backup folder is on another disk.

The backup folder is `PHORESIS_BACKUP_DIR`; by default `backups/` next to the media archive (so on
the external disk), else in the data folder. If its disk is not connected the backup is skipped, and
`status` says so. The same job rotates logs above 20 MB. With `PHORESIS_AUTO_UPDATE=release` it also
moves to the latest release tag after the backup.

## Files

| Path | What |
|---|---|
| `<checkout>/.env` | configuration and secrets (mode 600); see `.env.mac.example` |
| `~/Library/Application Support/Phoresis/media` | uploads, display images, thumbnails |
| `.../staticfiles`, `.../redis`, `.../caddy`, `.../run` | collected static files, Redis data, Caddy's authority and certificates, generated configs |
| `.../logs/*.log` | one log per service |
| `~/Library/LaunchAgents/local.phoresis.*.plist` | the services (no secret inside) |

## Known limits

- **Band detection is not bit-identical to the Windows install.** On Apple Silicon one frozen
  regression test of the classical detector
  (`test_default_hybrid_keeps_the_bands_validated_on_real_gels`) returns a different box for its
  faintest synthetic band: the gap-fill places it at y=320, 31 rows high, instead of y=321, 16 rows
  high. The cause is a floating-point tie in the d1/d2 gap-fill step, which arm64 and x86-64 break
  differently; it is not caused by CLAHE. The test holds both values, one per architecture, with
  x86-64 as the reference. Separately, OpenCV's CLAHE output differs by one grey level on arm64,
  which changed the result on about 1 % of simulated noisy lanes (a box a few rows higher or lower,
  a centre moved by 3 px at most). The detector has not been re-validated on real gels on a Mac.
- **Full Disk Access is tied to the interpreter's path.** A new Python patch version installed by uv
  changes that path; `status` then reports that the running service cannot use the archive disk, and
  `disk-access` prints the new path.
- **`phoresis.local` is announced by this Mac** (mDNS). Windows computers without Bonjour may need
  the Mac's IP address in their hosts file.
