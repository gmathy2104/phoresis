#!/bin/bash
# Phoresis on a Mac (Apple Silicon), without Docker: native processes kept alive by launchd.
# Design and operator guide: docs/INSTALL-MAC.md. The Windows / Docker scripts are untouched.
#
#   scripts/mac/phoresis.sh install        first install, or re-run after changing .env (idempotent)
#   scripts/mac/phoresis.sh status         services, URL, sleep, storage, last backup
#   scripts/mac/phoresis.sh restart        restart everything, migrations included
#   scripts/mac/phoresis.sh stop | start   stop / start the services (they stay installed)
#   scripts/mac/phoresis.sh update         pull the code, rebuild, migrate, restart (--release: latest tag)
#   scripts/mac/phoresis.sh logs [NAME]    follow a log: web (default), worker, beat, caddy, redis, mdns, nightly
#   scripts/mac/phoresis.sh backup         database dump + media mirror, now
#   scripts/mac/phoresis.sh restore DIR    restore a backup snapshot (asks for confirmation)
#   scripts/mac/phoresis.sh archive-disk PATH   use PATH (a folder on an external disk) as the media archive
#   scripts/mac/phoresis.sh extra-host add|remove NAME   one more name to answer on (a VPN name); extra-host list
#   scripts/mac/phoresis.sh shared-caddy use DIR [PORT] | off | status   be served by another app's Caddy (no port in the URL)
#   scripts/mac/phoresis.sh storage ...    manage.py media_storage (status, archive, restore, verify)
#   scripts/mac/phoresis.sh manage ...     any manage.py command, with the service's environment
#   scripts/mac/phoresis.sh trust          how to make this Mac (and others) trust the HTTPS certificate
#   scripts/mac/phoresis.sh disk-access    how to let the services read the external disk (macOS privacy)
#   scripts/mac/phoresis.sh uninstall      remove the services (data, database and .env are kept)
#
# Options of install: --yes (no questions: install missing Homebrew tools, keep defaults)
#
# Runs next to other apps on the same Mac (CamHub): its own ports, its own Redis, its own database
# in the shared Homebrew PostgreSQL, its own launchd labels. One program only can hold port 443:
# with `shared-caddy`, the Caddy of the app that holds it serves Phoresis too, under its own name.
# Written for the stock /bin/bash 3.2.
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
ENV_FILE="${PHORESIS_ENV_FILE:-$ROOT/.env}"
LABEL_PREFIX="${PHORESIS_LABEL_PREFIX:-local.phoresis}"
DOMAIN="gui/$(id -u)"
AGENTS_DIR="$HOME/Library/LaunchAgents"
# Started in this order, stopped in reverse. `nightly` is a timer, not a daemon.
SERVICES="redis web worker beat caddy mdns"
ALL_AGENTS="$SERVICES nightly"
VENV="$ROOT/.venv/bin"

COMMAND="${1:-}"
[ $# -gt 0 ] && shift

# ───────────────────────── output ─────────────────────────
if [ -t 1 ]; then
  BOLD=$'\033[1m' GREEN=$'\033[32m' YELLOW=$'\033[33m' RED=$'\033[31m' CYAN=$'\033[36m' DIM=$'\033[2m' RESET=$'\033[0m'
else
  BOLD="" GREEN="" YELLOW="" RED="" CYAN="" DIM="" RESET=""
fi
title() { printf '\n%s==> %s%s\n' "$BOLD" "$*" "$RESET"; }
ok() { printf '    %s[OK]%s %s\n' "$GREEN" "$RESET" "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '    %s[WARN]%s %s\n' "$YELLOW" "$RESET" "$*"; }
fail() {
  printf '    %s[ERROR]%s %s\n' "$RED" "$RESET" "$*" >&2
  exit 1
}
usage() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; }

# ───────────────────────── .env ─────────────────────────
# KEY=VALUE lines; everything after the first "=" is the value (spaces allowed, optional quotes).
env_get() { # env_get KEY [DEFAULT]
  local value=""
  if [ -f "$ENV_FILE" ]; then
    value="$(awk -v key="$1" '
      /^[[:space:]]*#/ { next }
      { eq = index($0, "="); if (eq < 2) next
        k = substr($0, 1, eq - 1); gsub(/^[[:space:]]+|[[:space:]]+$/, "", k)
        if (k == key) { v = substr($0, eq + 1); gsub(/^[[:space:]]+|[[:space:]]+$/, "", v); found = v } }
      END { print found }' "$ENV_FILE")"
    case "$value" in
      \"*\") value="${value#\"}" value="${value%\"}" ;;
      \'*\') value="${value#\'}" value="${value%\'}" ;;
    esac
  fi
  printf '%s' "${value:-${2:-}}"
}

env_set() { # env_set KEY VALUE : replaces the line or appends it; the file stays 0600
  local tmp
  tmp="$(mktemp "$ENV_FILE.XXXXXX")"
  if [ -f "$ENV_FILE" ]; then
    awk -v key="$1" '
      { eq = index($0, "="); k = substr($0, 1, eq - 1); gsub(/^[[:space:]]+|[[:space:]]+$/, "", k)
        if (eq >= 2 && k == key && $0 !~ /^[[:space:]]*#/) next
        print }' "$ENV_FILE" >"$tmp"
  fi
  printf '%s=%s\n' "$1" "$2" >>"$tmp"
  chmod 600 "$tmp"
  mv -f "$tmp" "$ENV_FILE"
}

env_default() { # env_default KEY VALUE : set only when absent or empty
  [ -n "$(env_get "$1")" ] || env_set "$1" "$2"
}

load_env() { # export every key of .env, then the values derived from it
  [ -f "$ENV_FILE" ] || fail "$ENV_FILE not found: run scripts/mac/phoresis.sh install"
  local line key value
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in '' | \#* | [[:space:]]*\#*) continue ;; esac
    case "$line" in *=*) ;; *) continue ;; esac
    key="${line%%=*}"
    key="$(printf '%s' "$key" | tr -d '[:space:]')"
    case "$key" in '' | *[!A-Za-z0-9_]*) continue ;; esac
    value="$(env_get "$key")"
    export "$key=$value"
  done <"$ENV_FILE"
  derive
}

extra_hostnames() { # PHORESIS_EXTRA_HOSTNAMES (comma separated) as words, lower-cased
  printf '%s' "${PHORESIS_EXTRA_HOSTNAMES:-}" | tr 'A-Z,' 'a-z ' | tr -s '[:space:]' ' '
}

all_hostnames() { printf '%s %s' "$HOSTNAME_PUBLIC" "$(extra_hostnames)"; }

origin_of() { # https://NAME, with the port when it is not 443
  if [ "$HTTPS_PORT" = 443 ]; then printf 'https://%s' "$1"; else printf 'https://%s:%s' "$1" "$HTTPS_PORT"; fi
}

write_host_settings() { # DJANGO_ALLOWED_HOSTS and DJANGO_CSRF_TRUSTED_ORIGINS, from the names and the port
  local name hosts="" origins=""
  for name in $(all_hostnames); do
    hosts="$hosts${hosts:+,}$name"
    origins="$origins${origins:+,}$(origin_of "$name")"
  done
  env_set DJANGO_ALLOWED_HOSTS "$hosts,127.0.0.1"
  env_set DJANGO_CSRF_TRUSTED_ORIGINS "$origins"
}

shared_caddy() { [ -n "${SHARED_DIR:-}" ]; }
shared_site_file() { printf '%s/%s.caddy' "$SHARED_DIR" "${LABEL_PREFIX#local.}"; }

derive() { # paths and ports every command needs; .env wins when it sets them
  DATA_DIR="${PHORESIS_DATA_DIR:-$HOME/Library/Application Support/Phoresis}"
  RUN_DIR="$DATA_DIR/run"
  LOG_DIR="$DATA_DIR/logs"
  export MEDIA_ROOT="${MEDIA_ROOT:-$DATA_DIR/media}"
  export STATIC_ROOT="${STATIC_ROOT:-$DATA_DIR/staticfiles}"
  HOSTNAME_PUBLIC="${PHORESIS_HOSTNAME:-phoresis.local}"
  HTTPS_PORT="${PHORESIS_HTTPS_PORT:-8443}"
  WEB_PORT="${PHORESIS_WEB_PORT:-8710}"
  ARCHIVE_ROOT="${PHORESIS_MEDIA_ARCHIVE_ROOT:-}"
  # Set: no Caddy of our own, our site is a file in that folder, read by another app's Caddy.
  SHARED_DIR="${PHORESIS_SHARED_CADDY_DIR:-}"
  if shared_caddy; then SERVICES="redis web worker beat mdns"; else SERVICES="redis web worker beat caddy mdns"; fi
  ALL_AGENTS="$SERVICES nightly"
  if [ "$HTTPS_PORT" = 443 ]; then BASE_URL="https://$HOSTNAME_PUBLIC"; else BASE_URL="https://$HOSTNAME_PUBLIC:$HTTPS_PORT"; fi
  export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-phoresis.settings.prod}"
  export PYTHONPATH="$ROOT/src"
  export PYTHONUNBUFFERED=1
  # gunicorn --preload and Celery prefork fork after Objective-C frameworks are loaded; macOS kills
  # such a child the first time it resolves a host name over the network. Learned on CamHub.
  export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
}

volume_of() { # /Volumes/<name> for a path on an external volume, else nothing
  case "$1" in /Volumes/*/*) printf '/Volumes/%s' "$(printf '%s' "${1#/Volumes/}" | cut -d/ -f1)" ;; esac
}

volume_mounted() { # true unless PATH is under /Volumes/<name> and that volume is not mounted
  local volume
  volume="$(volume_of "$1")"
  [ -z "$volume" ] || mount | grep -qF " on $volume ("
}

# ───────────────────────── launchd ─────────────────────────
label() { printf '%s.%s' "$LABEL_PREFIX" "$1"; }
plist_path() { printf '%s/%s.plist' "$AGENTS_DIR" "$(label "$1")"; }
loaded() { launchctl print "$DOMAIN/$(label "$1")" >/dev/null 2>&1; }
service_field() { # service_field NAME FIELD
  launchctl print "$DOMAIN/$(label "$1")" 2>/dev/null |
    awk -F' = ' -v key="$2" '$1 == "\t" key { print $2; exit }' || true
}

service_path() { # launchd only gives /usr/bin:/bin:/usr/sbin:/sbin
  local tool found dir path=""
  for tool in uv brew caddy redis-server pg_dump node git; do
    found="$(command -v "$tool" 2>/dev/null || true)"
    [ -n "$found" ] || continue
    dir="$(dirname "$found")"
    case ":$path:" in *":$dir:"*) ;; *) path="${path:+$path:}$dir" ;; esac
  done
  for dir in /opt/homebrew/bin /opt/homebrew/sbin /usr/local/bin /usr/bin /bin /usr/sbin /sbin; do
    case ":$path:" in *":$dir:"*) ;; *) path="${path:+$path:}$dir" ;; esac
  done
  printf '%s' "$path"
}

python_real() { "$VENV/python" -c 'import os, sys; print(os.path.realpath(sys.executable))'; }

xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

write_plist() { # write_plist NAME : no secret in it, everything is read from .env at start
  local name="$1" file schedule program extra_env=""
  file="$(plist_path "$name")"
  program="		<string>/bin/bash</string>
		<string>$(xml "$ROOT/scripts/mac/phoresis.sh")</string>
		<string>run</string>
		<string>$name</string>"
  if [ "$name" = nightly ]; then
    # Started THROUGH Phoresis' Python, which stays the parent of bash, rsync and pg_dump: macOS
    # checks the permission to read an external disk against the program launchd started, so the
    # one granted to that Python (disk-access) covers the backup too. web / worker / beat become
    # that same Python by exec.
    program="		<string>$(xml "$(python_real)")</string>
		<string>-c</string>
		<string>import subprocess, sys; sys.exit(subprocess.call(sys.argv[1:]))</string>
$program"
    schedule="	<key>StartCalendarInterval</key>
	<dict><key>Hour</key><integer>2</integer><key>Minute</key><integer>30</integer></dict>"
  else
    schedule="	<key>RunAtLoad</key>
	<true/>
	<key>KeepAlive</key>
	<true/>
	<key>ThrottleInterval</key>
	<integer>15</integer>
	<key>ExitTimeOut</key>
	<integer>30</integer>
	<key>ProcessType</key>
	<string>Interactive</string>"
  fi
  [ "$ENV_FILE" = "$ROOT/.env" ] || extra_env="		<key>PHORESIS_ENV_FILE</key>
		<string>$(xml "$ENV_FILE")</string>
"
  [ "$LABEL_PREFIX" = local.phoresis ] || extra_env="$extra_env		<key>PHORESIS_LABEL_PREFIX</key>
		<string>$(xml "$LABEL_PREFIX")</string>
"
  local tmp
  tmp="$(mktemp "$AGENTS_DIR/.$(label "$name").XXXXXX")"
  cat >"$tmp" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>$(label "$name")</string>
	<key>ProgramArguments</key>
	<array>
$program
	</array>
	<key>WorkingDirectory</key>
	<string>$(xml "$ROOT")</string>
$schedule
	<key>Umask</key>
	<integer>63</integer>
	<key>EnvironmentVariables</key>
	<dict>
		<key>PATH</key>
		<string>$(xml "$(service_path)")</string>
		<key>LANG</key>
		<string>en_US.UTF-8</string>
$extra_env	</dict>
	<key>StandardOutPath</key>
	<string>$(xml "$LOG_DIR/$name.log")</string>
	<key>StandardErrorPath</key>
	<string>$(xml "$LOG_DIR/$name.log")</string>
</dict>
</plist>
EOF
  plutil -lint -s "$tmp" || {
    rm -f "$tmp"
    fail "invalid plist for $name (bug in scripts/mac/phoresis.sh)"
  }
  chmod 644 "$tmp"
  mv -f "$tmp" "$file"
}

boot_out() { # boot_out NAME : stop and unload, wait until launchd is done with it
  local i
  loaded "$1" || return 0
  launchctl bootout "$DOMAIN/$(label "$1")" 2>/dev/null || true
  for i in $(seq 1 60); do
    loaded "$1" || return 0
    sleep 0.5
  done
  fail "launchd did not stop $(label "$1") in 30 s: launchctl print $DOMAIN/$(label "$1")"
}

boot_in() { # boot_in NAME
  local file
  file="$(plist_path "$1")"
  [ -f "$file" ] || fail "$(label "$1") is not installed: scripts/mac/phoresis.sh install"
  launchctl enable "$DOMAIN/$(label "$1")"
  launchctl bootstrap "$DOMAIN" "$file" ||
    fail "launchd refused $(label "$1"). Check System Settings > General > Login Items (Allow in the Background)."
}

# The nightly timer is left alone by restart and update: an update started BY the nightly job would
# otherwise unload, and so kill, itself. Only stop / uninstall / install touch it (ALL_AGENTS).
stop_services() { # stop_services [NAMES] (default: the daemons)
  local name reversed=""
  for name in ${1:-$SERVICES}; do reversed="$name $reversed"; done
  for name in $reversed; do boot_out "$name"; done
}

start_services() { # start_services [NAMES] (default: everything installed)
  local name
  mkdir -p "$LOG_DIR"
  for name in ${1:-$ALL_AGENTS}; do
    loaded "$name" || boot_in "$name"
  done
}

wait_ready() {
  local i tries=90
  shared_caddy && tries=30
  printf '    Waiting for the app '
  for i in $(seq 1 "$tries"); do
    # Through Caddy, as a browser does: it only forwards once its own health check has passed.
    if curl -fsSk -o /dev/null --max-time 2 --resolve "$HOSTNAME_PUBLIC:$HTTPS_PORT:127.0.0.1" "$BASE_URL/healthz/live/" 2>/dev/null; then
      printf '\n'
      ok "$BASE_URL answers (${i} s)"
      return 0
    fi
    [ $((i % 5)) = 0 ] && printf '.'
    sleep 1
  done
  printf '\n'
  if shared_caddy; then
    warn "$BASE_URL is not served yet. Phoresis itself: scripts/mac/phoresis.sh status"
    shared_caddy_todo
  else
    warn "Not answering after 90 s: scripts/mac/phoresis.sh logs web"
  fi
}

# ───────────────────────── install pieces ─────────────────────────
need_brew() { # need_brew FORMULA... : install what is missing, after asking
  local formula missing=""
  for formula in "$@"; do
    case "$formula" in
      uv | caddy | node) command -v "$formula" >/dev/null 2>&1 || missing="$missing $formula" ;;
      redis) command -v redis-server >/dev/null 2>&1 || missing="$missing redis" ;;
      git-lfs) command -v git-lfs >/dev/null 2>&1 || missing="$missing git-lfs" ;;
      postgresql@*) command -v psql >/dev/null 2>&1 || missing="$missing $formula" ;;
    esac
  done
  [ -n "$missing" ] || return 0
  command -v brew >/dev/null 2>&1 || fail "Homebrew is required (https://brew.sh), then: brew install$missing"
  if [ "$ASSUME_YES" != 1 ]; then
    printf '    Missing tools:%s. Install them with Homebrew now? [Y/n] ' "$missing"
    local answer
    read -r answer
    case "$answer" in n | N | no | NO) fail "Install them, then re-run: brew install$missing" ;; esac
  fi
  # shellcheck disable=SC2086
  brew install $missing
}

random_secret() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${1:-50}" || true; }

port_free() { ! lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

pick_port() { # pick_port PREFERRED... : first free one
  local port
  for port in "$@"; do
    if port_free "$port"; then
      printf '%s' "$port"
      return 0
    fi
  done
  fail "none of these ports is free: $*"
}

ask() { # ask PROMPT [DEFAULT]
  local answer
  printf '    %s%s: ' "$1" "${2:+ [$2]}" >&2
  read -r answer
  printf '%s' "${answer:-${2:-}}"
}

ask_secret() {
  local first second
  while :; do
    printf '    %s: ' "$1" >&2
    read -rs first
    printf '\n    Again: ' >&2
    read -rs second
    printf '\n' >&2
    [ -n "$first" ] && [ "$first" = "$second" ] && break
    printf '    They differ (or are empty), try again.\n' >&2
  done
  printf '%s' "$first"
}

psql_admin() { psql -X -q -h 127.0.0.1 -p "$PG_PORT" -d postgres -v ON_ERROR_STOP=1 "$@"; }

find_postgres() { # sets PG_PORT: the port of .env, else the newest server answering on 5432 / 5433
  local port version best=0
  PG_PORT="$(env_get DB_PORT)"
  if [ -n "$PG_PORT" ]; then
    pg_isready -q -h 127.0.0.1 -p "$PG_PORT" || fail "PostgreSQL does not answer on 127.0.0.1:$PG_PORT (DB_PORT of .env)"
    return 0
  fi
  for port in 5432 5433 5434; do
    pg_isready -q -h 127.0.0.1 -p "$port" 2>/dev/null || continue
    version="$(psql -X -Atq -h 127.0.0.1 -p "$port" -d postgres -c 'show server_version_num' 2>/dev/null || echo 0)"
    if [ "${version:-0}" -gt "$best" ]; then
      best="$version"
      PG_PORT="$port"
    fi
  done
  [ -n "$PG_PORT" ] || fail "No PostgreSQL answers on 127.0.0.1 (5432-5434) as $(id -un). Start it: brew services start postgresql@18"
}

setup_database() {
  local name user password exists
  find_postgres
  name="$(env_get DB_NAME phoresis)"
  user="$(env_get DB_USER phoresis)"
  password="$(env_get DB_PASSWORD)"
  case "$name$user" in *[!A-Za-z0-9_]*) fail "DB_NAME / DB_USER may only hold letters, digits and _" ;; esac
  exists="$(psql_admin -At -c "select 1 from pg_roles where rolname = '$user'")"
  if [ -z "$password" ]; then
    # No password on record (first install, or .env lost): the role is ours, give it a new one.
    password="$(random_secret 32)"
    if [ -n "$exists" ]; then
      psql_admin -v pw="$password" <<<"ALTER ROLE \"$user\" LOGIN PASSWORD :'pw';"
      info "Role $user existed: new password set"
    fi
  fi
  if [ -z "$exists" ]; then
    psql_admin -v pw="$password" <<<"CREATE ROLE \"$user\" LOGIN PASSWORD :'pw';"
  fi
  if [ -z "$(psql_admin -At -c "select 1 from pg_database where datname = '$name'")" ]; then
    psql_admin -c "CREATE DATABASE \"$name\" OWNER \"$user\""
  fi
  env_set DB_HOST 127.0.0.1
  env_set DB_PORT "$PG_PORT"
  env_set DB_NAME "$name"
  env_set DB_USER "$user"
  env_set DB_PASSWORD "$password"
  ok "PostgreSQL on port $PG_PORT: database $name, role $user"
}

lfs_models() { # the ML models are Git LFS files; without git-lfs a clone holds 134-byte pointers (AGENTS.md §4)
  local pointer=0 file
  for file in "$ROOT"/src/gel_analyzer/static/gel_analyzer/ml/*.onnx "$ROOT"/src/gel_analyzer/static/gel_analyzer/ml/sam/*; do
    [ -f "$file" ] || continue
    [ "$(stat -f %z "$file")" -lt 1024 ] && pointer=1
  done
  [ "$pointer" = 1 ] || return 0
  info "ML models are Git LFS pointers: fetching the real files"
  (cd "$ROOT" && git lfs install --local >/dev/null && git lfs pull) ||
    warn "git lfs pull failed: band detection will not work until it succeeds"
}

build_code() {
  title "Python environment"
  # Python 3.12 like the Docker image; --extra cpu is the Apple Silicon build of torch (MPS included).
  # A uv-managed interpreter, not Homebrew's: `brew upgrade` moves Homebrew's Python, which would break
  # the venv and drop the Full Disk Access given to it (disk-access).
  (cd "$ROOT" && UV_PYTHON_PREFERENCE=only-managed uv sync --frozen --no-dev --extra cpu --python 3.12)
  ok ".venv ready"
  title "Stylesheet"
  (cd "$ROOT" && npm ci --no-audit --no-fund && npm run build:css)
  ok "output.css built"
}

prepare() { # same order as docker/entrypoint.sh (AGENTS.md §7)
  title "Database migrations, static files, seeds"
  mkdir -p "$MEDIA_ROOT" "$STATIC_ROOT" "$RUN_DIR" "$LOG_DIR"
  cd "$ROOT"
  "$VENV/python" manage.py migrate --noinput
  "$VENV/python" manage.py collectstatic --noinput --clear --ignore "input.css" --ignore "tokens.css" >/dev/null
  "$VENV/python" manage.py seed_groups
  "$VENV/python" manage.py seed_ladder_templates
  "$VENV/python" manage.py create_initial_users --from-env --skip-existing
  if shared_caddy; then publish_site; fi
  ok "Application prepared"
}

# ───────────────────────── commands ─────────────────────────
cmd_install() {
  ASSUME_YES=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --yes | -y) ASSUME_YES=1 ;;
      *) fail "Unknown option: $1 (scripts/mac/phoresis.sh --help)" ;;
    esac
    shift
  done
  title "Phoresis on this Mac ($LABEL_PREFIX)"
  [ "$(uname -s)" = Darwin ] || fail "This script is for macOS. On Windows: scripts/install.ps1"
  if [ -f "$ROOT/.git" ] && [ "${PHORESIS_ALLOW_WORKTREE:-0}" != 1 ]; then
    fail "This folder is a git worktree: install from the main checkout (the services would point at a temporary folder)."
  fi

  case "$ROOT/" in "$HOME/Documents/"* | "$HOME/Desktop/"* | "$HOME/Downloads/"*)
    fail "macOS keeps background services out of Documents, Desktop and Downloads: move this folder (e.g. ~/phoresis)."
    ;;
  esac

  title "Tools"
  # PHORESIS_SKIP_LFS=1: a trial install that does not need the ML models (band detection disabled).
  if [ "${PHORESIS_SKIP_LFS:-0}" = 1 ]; then
    need_brew uv caddy redis node postgresql@18
    warn "Git LFS skipped: ML models not fetched"
  else
    need_brew uv caddy redis node git-lfs postgresql@18
    lfs_models
  fi
  ok "Tools present"

  title "Configuration ($ENV_FILE)"
  if [ ! -f "$ENV_FILE" ]; then
    : >"$ENV_FILE"
    chmod 600 "$ENV_FILE"
    if [ "$ASSUME_YES" = 1 ]; then
      fail "--yes needs an existing .env with ADMIN_EMAIL and ADMIN_PASSWORD (see .env.mac.example)"
    fi
    info "First install: the two accounts created at first start."
    env_set ADMIN_EMAIL "$(ask "Admin email")"
    env_set ADMIN_PASSWORD "$(ask_secret "Admin password")"
    env_set PRIMARY_USER_EMAIL "$(ask "Lab user email")"
    env_set PRIMARY_USER_PASSWORD "$(ask_secret "Lab user password")"
    env_set PRIMARY_USER_FULL_NAME "$(ask "Lab user full name")"
  else
    info ".env exists: kept, missing values completed"
  fi
  chmod 600 "$ENV_FILE"
  env_default DJANGO_SETTINGS_MODULE phoresis.settings.prod
  env_default DJANGO_SECRET_KEY "$(random_secret 50)"
  env_default DJANGO_DEBUG false
  env_default PHORESIS_HOSTNAME phoresis.local
  # 443 belongs to whichever app took it first (CamHub on this Mac): Phoresis then answers on 8443.
  # Behind another app's Caddy (PHORESIS_SHARED_CADDY_DIR, see shared-caddy): that Caddy's port.
  if [ -n "$(env_get PHORESIS_SHARED_CADDY_DIR)" ]; then env_default PHORESIS_HTTPS_PORT 443; fi
  env_default PHORESIS_HTTPS_PORT "$(pick_port 443 8443 8444 8445)"
  env_default PHORESIS_WEB_PORT "$(pick_port 8710 8711 8712)"
  env_default REDIS_HOST 127.0.0.1
  env_default REDIS_PORT "$(pick_port 6390 6391 6392)"
  env_default REDIS_PASSWORD "$(random_secret 32)"
  env_default REDIS_DB_CELERY 0
  env_default REDIS_DB_CACHE 1
  env_default TZ Europe/Brussels
  env_default PHORESIS_MEDIA_HOT_QUOTA_GB 50
  env_default PHORESIS_MEDIA_MIN_FREE_GB 20
  env_default PHORESIS_BACKUP_KEEP 14
  # Staff and superusers set up an authenticator app at their first sign-in (accounts/docs/README.md).
  env_default PHORESIS_REQUIRE_2FA staff
  setup_database
  # Derived from the host names and the port, rewritten at each install so they follow a change.
  load_env
  write_host_settings
  load_env
  mkdir -p "$DATA_DIR" "$RUN_DIR" "$LOG_DIR" "$MEDIA_ROOT" "$AGENTS_DIR"
  ok "Data folder: $DATA_DIR"

  build_code

  title "Services"
  stop_services "$ALL_AGENTS"
  if shared_caddy; then drop_own_caddy; fi
  prepare
  local name
  for name in $ALL_AGENTS; do write_plist "$name"; done
  start_services
  ok "launchd agents loaded: start now and at every login"
  wait_ready

  title "Done"
  info "Open        $BASE_URL"
  info "Certificate scripts/mac/phoresis.sh trust   (once, so browsers accept it)"
  if ! shared_caddy && [ "$HTTPS_PORT" != 443 ]; then
    info "No port     another app holds 443. To be served by its Caddy, as https://$HOSTNAME_PUBLIC:"
    info "            scripts/mac/phoresis.sh shared-caddy use <its sites folder>"
  fi
  if [ -z "$ARCHIVE_ROOT" ]; then
    info "Storage     gels stay on this Mac. To move the oldest to an external disk:"
    info "            scripts/mac/phoresis.sh archive-disk \"/Volumes/<disk>/Phoresis/media\""
  fi
  info "macOS may show \"Background Items Added\": leave it allowed."
  info "A Mac mini that restarts alone needs automatic login (System Settings > Users & Groups)."
  printf '\n'
}

cmd_uninstall() {
  load_env
  title "Removing the Phoresis services ($LABEL_PREFIX)"
  stop_services "$ALL_AGENTS"
  local name
  for name in $ALL_AGENTS; do rm -f "$(plist_path "$name")"; done
  ok "launchd agents removed"
  if shared_caddy && [ -f "$(shared_site_file)" ]; then
    rm -f "$(shared_site_file)"
    info "Site file removed from $SHARED_DIR: restart the app that runs the shared Caddy"
  fi
  info "Kept: $DATA_DIR (media, backups, logs), the database, $ENV_FILE"
  printf '\n'
}

cmd_stop() {
  load_env
  stop_services "$ALL_AGENTS"
  ok "Phoresis stopped (it starts again at the next login; uninstall to prevent that)"
}

cmd_start() {
  load_env
  start_services
  wait_ready
}

cmd_restart() {
  load_env
  title "Restarting Phoresis"
  stop_services
  prepare
  start_services
  wait_ready
}

cmd_update() {
  local release=0
  [ "${1:-}" = --release ] && release=1
  load_env
  title "Updating Phoresis"
  cd "$ROOT"
  [ -z "$(git status --porcelain --untracked-files=no)" ] || fail "Local changes in $ROOT: commit or discard them first"
  local before after
  before="$(git rev-parse HEAD)"
  if [ "$release" = 1 ]; then
    git fetch --tags --quiet origin
    local tag
    tag="$(git tag --list 'v[0-9]*' --sort=-v:refname | head -1)"
    [ -n "$tag" ] || fail "No release tag found"
    git checkout --quiet "$tag"
    info "Release $tag"
  else
    git pull --ff-only --quiet
  fi
  after="$(git rev-parse HEAD)"
  if [ "$before" = "$after" ] && [ "${PHORESIS_FORCE_UPDATE:-0}" != 1 ]; then
    ok "Already up to date ($(git describe --tags --always))"
    return 0
  fi
  lfs_models
  cmd_backup_quiet || warn "Backup before update failed: continuing"
  build_code
  stop_services
  prepare
  start_services
  wait_ready
  ok "Updated to $(git describe --tags --always)"
}

backup_dir() { # PHORESIS_BACKUP_DIR, else next to the media archive, else in the data folder
  if [ -n "${PHORESIS_BACKUP_DIR:-}" ]; then
    printf '%s' "$PHORESIS_BACKUP_DIR"
  elif [ -n "$ARCHIVE_ROOT" ]; then
    printf '%s/backups' "$(dirname "$ARCHIVE_ROOT")"
  else
    printf '%s/backups' "$DATA_DIR"
  fi
}

pg_tool() { # pg_tool pg_dump|pg_restore : the binary of the SERVER's major version
  # Several PostgreSQL versions can be installed side by side, and pg_dump refuses a newer server.
  local major dir
  major="$(PGPASSWORD="$DB_PASSWORD" psql -X -Atq -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    -c 'show server_version_num' 2>/dev/null | cut -c1-2)"
  for dir in "/opt/homebrew/opt/postgresql@$major/bin" "/usr/local/opt/postgresql@$major/bin"; do
    if [ -n "$major" ] && [ -x "$dir/$1" ]; then
      printf '%s' "$dir/$1"
      return 0
    fi
  done
  printf '%s' "$1"
}

same_disk() { [ "$(stat -f %d "$1")" = "$(stat -f %d "$2")" ]; }

cmd_backup() {
  load_env
  title "Backup"
  local dest stamp snapshot keep
  dest="$(backup_dir)"
  # Never create a folder on a disk that is not there: the path would land on the system disk.
  volume_mounted "$dest" || fail "$(volume_of "$dest") is not connected: backup skipped"
  stamp="$(date '+%Y%m%d-%H%M%S')"
  snapshot="$dest/$stamp"
  mkdir -p "$snapshot" "$MEDIA_ROOT"
  if ! PGPASSWORD="$DB_PASSWORD" "$(pg_tool pg_dump)" -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -Fc \
    -f "$snapshot/phoresis.dump.part" "$DB_NAME"; then
    rm -rf "$snapshot" # no half snapshot: the newest folder is always a complete one
    fail "pg_dump failed: nothing was backed up"
  fi
  mv "$snapshot/phoresis.dump.part" "$snapshot/phoresis.dump"
  (cd "$ROOT" && git describe --tags --always 2>/dev/null || echo unknown) >"$snapshot/VERSION"
  ok "Database: $snapshot/phoresis.dump ($(du -h "$snapshot/phoresis.dump" | cut -f1 | tr -d ' '))"
  if same_disk "$dest" "$MEDIA_ROOT"; then
    info "Media not copied: the backup folder is on the same disk as the media (set PHORESIS_BACKUP_DIR to another disk)"
  else
    # One mirror, not one copy per night: what is on this Mac, as it is now. Archived originals are
    # not in it (they already live on the archive disk, and only there).
    mkdir -p "$dest/media"
    rsync -a --delete "$MEDIA_ROOT/" "$dest/media/"
    ok "Media mirrored to $dest/media ($(du -sh "$dest/media" | cut -f1 | tr -d ' '))"
  fi
  keep="${PHORESIS_BACKUP_KEEP:-14}"
  # Snapshot folders are named by date: the oldest sort first.
  find "$dest" -mindepth 1 -maxdepth 1 -type d -name '20[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]' | sort |
    awk -v keep="$keep" '{ lines[NR] = $0 } END { for (i = 1; i <= NR - keep; i++) print lines[i] }' |
    while IFS= read -r old; do rm -rf "$old"; done
  ok "Kept the last $keep database dumps in $dest"
}

cmd_backup_quiet() { (cmd_backup) >/dev/null; }

cmd_restore() {
  local snapshot="${1:-}" answer
  load_env
  [ -n "$snapshot" ] || fail "Usage: scripts/mac/phoresis.sh restore DIR   (a dated folder of $(backup_dir))"
  [ -f "$snapshot/phoresis.dump" ] || fail "$snapshot/phoresis.dump not found"
  title "Restore from $snapshot"
  warn "The database $DB_NAME is replaced by the dump. Media files are copied back, none is deleted."
  printf '    Type RESTORE to continue: '
  read -r answer
  [ "$answer" = RESTORE ] || fail "Cancelled"
  stop_services
  PGPASSWORD="$DB_PASSWORD" "$(pg_tool pg_restore)" -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    --clean --if-exists --no-owner "$snapshot/phoresis.dump"
  ok "Database restored"
  if [ -d "$(dirname "$snapshot")/media" ]; then
    mkdir -p "$MEDIA_ROOT"
    rsync -a "$(dirname "$snapshot")/media/" "$MEDIA_ROOT/"
    ok "Media copied back"
  fi
  prepare
  start_services
  wait_ready
}

cmd_extra_host() { # add or remove a name Phoresis answers to, besides PHORESIS_HOSTNAME
  local action="${1:-}" name kept="" found=0 item
  name="$(printf '%s' "${2:-}" | tr 'A-Z' 'a-z')"
  load_env
  case "$action" in
    list)
      info "Main name:   $HOSTNAME_PUBLIC"
      kept="$(extra_hostnames)"
      info "Extra names: ${kept:-(none)}"
      return
      ;;
    add | remove) ;;
    *) fail "Usage: scripts/mac/phoresis.sh extra-host add|remove NAME   |   extra-host list" ;;
  esac
  case "$name" in
    '' | *[!a-z0-9.-]* | .* | -*) fail "Give a host name or an IP address (letters, digits, dots, dashes), without https:// or a port" ;;
  esac
  [ "$name" != "$HOSTNAME_PUBLIC" ] || fail "$name is already the main name"
  for item in $(extra_hostnames); do
    if [ "$item" = "$name" ]; then found=1; else kept="$kept${kept:+,}$item"; fi
  done
  if [ "$action" = add ]; then
    [ "$found" = 0 ] || { ok "$name is already an extra name"; return; }
    kept="$kept${kept:+,}$name"
  else
    [ "$found" = 1 ] || fail "$name is not an extra name"
  fi
  env_set PHORESIS_EXTRA_HOSTNAMES "$kept"
  load_env
  write_host_settings
  load_env
  if shared_caddy; then publish_site; fi
  if loaded web; then
    # Django reads the allowed hosts at start, Caddy its site names and certificates.
    for item in $(shared_caddy || printf caddy) web; do boot_out "$item"; done
    start_services
    wait_ready
  fi
  if [ "$action" = add ] && shared_caddy; then
    ok "$name added: the shared Caddy serves it once restarted, with a certificate that includes it"
    shared_caddy_todo
  elif [ "$action" = add ]; then
    ok "Phoresis now also answers on $(origin_of "$name")"
    info "The certificate for that name is signed by the same local authority: scripts/mac/phoresis.sh trust"
  else
    ok "$name removed"
  fi
}

cmd_archive_disk() {
  local path="${1:-}"
  load_env
  [ -n "$path" ] || fail "Usage: scripts/mac/phoresis.sh archive-disk \"/Volumes/<disk>/Phoresis/media\""
  case "$path" in /*) ;; *) fail "Give an absolute path" ;; esac
  volume_mounted "$path" || fail "$(volume_of "$path") is not connected"
  title "Media archive: $path"
  env_set PHORESIS_MEDIA_ARCHIVE_ROOT "$path"
  load_env
  (cd "$ROOT" && "$VENV/python" manage.py media_storage prepare)
  if loaded web; then
    # Django, Celery and Caddy all read the archive path at start.
    local name
    for name in caddy beat worker web; do boot_out "$name"; done
    start_services
    wait_ready
  fi
  (cd "$ROOT" && "$VENV/python" manage.py media_storage status)
  if volume_of "$path" | grep -q .; then
    info "External disk: allow the services to read it, once -> scripts/mac/phoresis.sh disk-access"
  fi
  info "Every night at 04:15, originals older than ${PHORESIS_MEDIA_ARCHIVE_MIN_AGE_DAYS:-30} days move there once"
  info "gels use more than ${PHORESIS_MEDIA_HOT_QUOTA_GB:-50} GB on this Mac. They exist only on that disk: back it up."
}

cmd_manage() {
  load_env
  cd "$ROOT"
  exec "$VENV/python" manage.py "$@"
}

cmd_logs() {
  load_env
  local name="${1:-web}"
  if [ "$name" = caddy ] && shared_caddy; then
    fail "Phoresis has no Caddy of its own here: read the log of the app that runs the shared one"
  fi
  [ -f "$LOG_DIR/$name.log" ] || fail "No log named $name in $LOG_DIR"
  exec tail -n 100 -F "$LOG_DIR/$name.log"
}

cmd_disk_access() {
  load_env
  title "Access to the external disk"
  info "macOS does not let a background service read an external disk until you allow it."
  info "Phoresis needs it for ONE program, its Python interpreter:"
  printf '\n      %s\n\n' "$(python_real)"
  info "System Settings > Privacy & Security > Full Disk Access > \"+\""
  info "then press Cmd+Shift+G, paste the path above, Open, and switch it on."
  info "Then: scripts/mac/phoresis.sh restart"
  info "Needed again if that path changes (a new Python version after an update): status says so."
}

ca_cert() { printf '%s/caddy/caddy/pki/authorities/local/root.crt' "$DATA_DIR"; }

cmd_trust() {
  load_env
  local cert
  cert="$(ca_cert)"
  title "HTTPS certificate"
  if shared_caddy; then
    info "Phoresis is served by another app's Caddy (site file in $SHARED_DIR):"
    info "the certificate comes from that app's local authority, not from Phoresis."
    info "A device that already trusts that app accepts $BASE_URL as it is;"
    info "a new device trusts that app's authority, the way that app documents it."
    return
  fi
  [ -f "$cert" ] || fail "$cert not found yet: start Phoresis and open $BASE_URL once"
  info "Phoresis signs its certificate with its own local authority. To trust it on this Mac"
  info "(asks for your password; run it yourself, the script does not use sudo):"
  printf '\n      sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "%s"\n\n' "$cert"
  info "On another computer or a phone: copy that root.crt file there and trust it."
  info "Fingerprint: $(openssl x509 -in "$cert" -noout -fingerprint -sha256 | cut -d= -f2)"
}

cmd_status() {
  load_env
  title "Phoresis ($LABEL_PREFIX)"
  local name state pid
  for name in $SERVICES; do
    if ! [ -f "$(plist_path "$name")" ]; then
      warn "$(printf '%-8s' "$name") not installed"
    elif ! loaded "$name"; then
      warn "$(printf '%-8s' "$name") installed, stopped"
    else
      state="$(service_field "$name" state)"
      pid="$(service_field "$name" pid)"
      if [ "$state" = running ]; then
        ok "$(printf '%-8s' "$name") running ${DIM}(pid $pid)${RESET}"
      else
        warn "$(printf '%-8s' "$name") ${state:-?} (last exit: $(service_field "$name" "last exit code")) : scripts/mac/phoresis.sh logs $name"
      fi
    fi
  done
  if shared_caddy; then
    if [ -f "$(shared_site_file)" ]; then
      ok "caddy    shared with another app ${DIM}($(shared_site_file))${RESET}"
    else
      warn "caddy    shared, but $(shared_site_file) is missing: scripts/mac/phoresis.sh restart"
    fi
  fi
  if loaded nightly; then ok "nightly  02:30 backup, log rotation"; else warn "nightly  not loaded"; fi

  title "Access"
  if curl -fsS -o /dev/null --max-time 3 "http://127.0.0.1:$WEB_PORT/healthz/live/" 2>/dev/null; then
    ok "Django answers on 127.0.0.1:$WEB_PORT"
  else
    warn "Django does not answer on 127.0.0.1:$WEB_PORT"
  fi
  if curl -fsSk -o /dev/null --max-time 3 --resolve "$HOSTNAME_PUBLIC:$HTTPS_PORT:127.0.0.1" "$BASE_URL/healthz/live/" 2>/dev/null; then
    ok "$BASE_URL"
  else
    warn "$BASE_URL does not answer"
    if shared_caddy; then shared_caddy_todo; fi
  fi
  if pmset -g assertions 2>/dev/null | grep -Eq "caffeinate asserting on behalf of Process ID $(service_field web pid)([^0-9]|\$)"; then
    ok "Sleep prevented while Phoresis runs (on mains power)"
  else
    warn "Sleep not prevented (caffeinate only holds on mains power)"
  fi

  title "Storage"
  if [ -x "$VENV/python" ]; then
    (cd "$ROOT" && "$VENV/python" manage.py media_storage status 2>/dev/null |
      grep -v ' | phoresis_core.logging_config | ' | sed 's/^/    /') || warn "media_storage status failed"
  fi
  if [ -n "$ARCHIVE_ROOT" ]; then
    # This terminal may read the disk while the background service may not: ask the service.
    case "$(curl -fsS --max-time 5 "http://127.0.0.1:$WEB_PORT/healthz/" 2>/dev/null)" in
      *'"media_archive": "ready"'*) ok "The running service reads the archive disk" ;;
      *'"media_archive"'*) warn "The running service cannot use the archive disk. If it is plugged in: scripts/mac/phoresis.sh disk-access" ;;
    esac
  fi
  local dest last
  dest="$(backup_dir)"
  if ! volume_mounted "$dest"; then
    warn "Backups: $(volume_of "$dest") is not connected"
  else
    last="$(find "$dest" -mindepth 1 -maxdepth 1 -type d -name '20*' 2>/dev/null | sort | tail -1)"
    if [ -n "$last" ]; then ok "Last backup: $last"; else warn "No backup yet in $dest (scripts/mac/phoresis.sh backup)"; fi
  fi
  printf '\n'
}

# ───────────────────────── launchd entry points ─────────────────────────
perf_cores() { sysctl -n hw.perflevel0.physicalcpu 2>/dev/null || sysctl -n hw.physicalcpu; }

site_block() { # site_block TLS_DIRECTIVE : the Phoresis site, for our own Caddy or a shared one
  local site="" name media_fallback=""
  # One site, every name it answers to: the .local one and the extra ones (a VPN name).
  for name in $(all_hostnames); do
    site="$site${site:+, }$(origin_of "$name")"
  done
  if [ -n "$ARCHIVE_ROOT" ]; then
    # Not on this Mac: Django reads it from the archive disk (phoresis_core.media_tiers.serve_media).
    # Caddy never opens the external disk itself, so only Python needs macOS' permission for it.
    media_fallback="
		handle {
			rewrite * /media{uri}
			reverse_proxy 127.0.0.1:$WEB_PORT
		}"
  fi
  cat <<EOF
$site {
	$1
	encode gzip zstd

	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options nosniff
		X-Frame-Options DENY
		Referrer-Policy strict-origin-when-cross-origin
		-Server
	}

	handle_path /static/* {
		root * "$STATIC_ROOT"
		file_server {
			precompressed gzip
		}
	}

	# Media, to signed-in users only (Django is asked first: accounts.views.media_auth_view):
	# this Mac first, then the archive disk (phoresis_core/media_tiers.py).
	handle_path /media/* {
		forward_auth 127.0.0.1:$WEB_PORT {
			uri /api/auth/media/
		}
		@here file {
			root "$MEDIA_ROOT"
		}
		handle @here {
			root * "$MEDIA_ROOT"
			file_server
		}$media_fallback
	}

	reverse_proxy 127.0.0.1:$WEB_PORT {
		health_uri /healthz/live/
		health_interval 10s
		health_timeout 5s
		health_status 200
		header_up X-Real-IP {remote_host}
	}
}
EOF
}

write_caddyfile() { # our own Caddy: its options, then the site with a certificate of its own authority
  {
    cat <<EOF
# Generated at each start by scripts/mac/phoresis.sh (run caddy): edit the script, not this file.
{
	admin off
	persist_config off
	skip_install_trust
	auto_https disable_redirects
	log {
		format console
		level WARN
	}
}

EOF
    site_block "tls internal"
  } >"$RUN_DIR/Caddyfile"
}

# ───────────────────────── shared Caddy ─────────────────────────
# One program only can hold port 443. When another app's Caddy holds it (CamHub), Phoresis hands it
# a site file instead of running its own: that Caddy imports every *.caddy of a folder and offers
# the snippet `shared_tls` (its certificate). Phoresis is then https://phoresis.local, no port.
publish_site() { # write our site into the shared folder; say so when it changed
  local file new
  file="$(shared_site_file)"
  [ -d "$SHARED_DIR" ] || fail "$SHARED_DIR not found (PHORESIS_SHARED_CADDY_DIR): scripts/mac/phoresis.sh shared-caddy off, or put it back"
  new="$(printf '# Written by %s (shared-caddy): edit the script, not this file.\n' "$ROOT/scripts/mac/phoresis.sh"
    site_block "import shared_tls")"
  if [ -f "$file" ] && [ "$(cat "$file")" = "$new" ]; then return 0; fi
  (umask 077 && printf '%s\n' "$new" >"$file.tmp" && mv "$file.tmp" "$file")
  info "Site file written: $file"
}

shared_caddy_todo() {
  info "The shared Caddy reads site files when it starts, and its certificate must hold every name"
  info "($(all_hostnames | tr -s ' ' | sed -e 's/ $//' -e 's/ /, /g')). With CamHub, in its folder:"
  info "    PKI_EXTRA_HOSTNAMES=<those names> in .env, then: make hub-restart"
}

drop_own_caddy() {
  if [ -f "$(plist_path caddy)" ] || loaded caddy; then
    boot_out caddy
    rm -f "$(plist_path caddy)"
    info "Phoresis' own Caddy removed (the shared one serves it)"
  fi
}

cmd_shared_caddy() {
  local action="${1:-}" dir="${2:-}" port="${3:-443}"
  load_env
  case "$action" in
    status)
      if shared_caddy; then
        info "Shared: site file $(shared_site_file), port $HTTPS_PORT, $BASE_URL"
      else
        info "Not shared: Phoresis runs its own Caddy on $BASE_URL"
      fi
      ;;
    use)
      [ -n "$dir" ] || fail "Usage: scripts/mac/phoresis.sh shared-caddy use DIR [PORT]   (CamHub: <its folder>/var/caddy-sites)"
      [ -d "$dir" ] || fail "$dir is not a folder: give the one the shared Caddy reads its sites from"
      case "$port" in '' | *[!0-9]*) fail "PORT is the HTTPS port of the shared Caddy (443)" ;; esac
      dir="$(cd "$dir" && pwd -P)"
      title "Phoresis behind the shared Caddy"
      env_set PHORESIS_SHARED_CADDY_DIR "$dir"
      env_set PHORESIS_HTTPS_PORT "$port"
      load_env
      write_host_settings
      load_env
      drop_own_caddy
      publish_site
      if loaded web; then
        boot_out web # Django reads its allowed hosts and trusted origins at start
        start_services
      fi
      ok "Phoresis is now $BASE_URL, served by the Caddy that reads $dir"
      shared_caddy_todo
      ;;
    off)
      shared_caddy || fail "Phoresis already runs its own Caddy"
      title "Phoresis back on its own Caddy"
      rm -f "$(shared_site_file)"
      info "Site file removed: restart the app that runs the shared Caddy, so it stops serving this name"
      env_set PHORESIS_SHARED_CADDY_DIR ""
      env_set PHORESIS_HTTPS_PORT "$(pick_port 443 8443 8444 8445)"
      load_env
      write_host_settings
      load_env
      write_plist caddy
      if loaded web; then
        boot_out web
        start_services
        wait_ready
      fi
      ok "Phoresis is now $BASE_URL (scripts/mac/phoresis.sh trust)"
      ;;
    *) fail "Usage: scripts/mac/phoresis.sh shared-caddy use DIR [PORT]   |   shared-caddy off   |   shared-caddy status" ;;
  esac
}

lan_ip() { # address of the default route's interface, 127.0.0.1 when offline
  local iface ip=""
  iface="$(route -n get default 2>/dev/null | awk '/interface:/ { print $2 }')"
  [ -n "$iface" ] && ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
  printf '%s' "${ip:-127.0.0.1}"
}

run_mdns() { # announce <hostname>.local on the network; re-announce when the address changes
  case "$HOSTNAME_PUBLIC" in *.local) ;; *)
    echo "mdns: $HOSTNAME_PUBLIC is not a .local name, nothing to announce"
    exec sleep 86400
    ;;
  esac
  local ip current child=""
  trap '[ -n "$child" ] && kill "$child" 2>/dev/null; exit 0' TERM INT
  ip=""
  while :; do
    current="$(lan_ip)"
    if [ "$current" != "$ip" ] || ! kill -0 "$child" 2>/dev/null; then
      [ -n "$child" ] && kill "$child" 2>/dev/null && wait "$child" 2>/dev/null
      ip="$current"
      echo "mdns: $(date '+%Y-%m-%d %H:%M:%S') announcing $HOSTNAME_PUBLIC -> $ip (port $HTTPS_PORT)"
      dns-sd -P Phoresis _https._tcp local "$HTTPS_PORT" "$HOSTNAME_PUBLIC" "$ip" >/dev/null 2>&1 &
      child=$!
    fi
    sleep 30 &
    wait $! || true
  done
}

run_nightly() {
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') nightly ==="
  (cmd_backup) || echo "nightly: backup failed"
  local file
  for file in "$LOG_DIR"/*.log; do
    [ -f "$file" ] || continue
    # copy-truncate: the services keep their (append-mode) file open
    if [ "$(stat -f %z "$file")" -gt $((20 * 1024 * 1024)) ]; then
      cp -f "$file" "$file.1" && : >"$file"
    fi
  done
  case "${PHORESIS_AUTO_UPDATE:-off}" in
    release) (cmd_update --release) || echo "nightly: update failed" ;;
    branch) (cmd_update) || echo "nightly: update failed" ;;
  esac
}

cmd_run() {
  local role="${1:-}"
  load_env
  mkdir -p "$RUN_DIR" "$LOG_DIR" "$MEDIA_ROOT"
  cd "$ROOT"
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') starting $role ==="
  case "$role" in
    redis)
      mkdir -p "$DATA_DIR/redis"
      # The password goes in a 0600 file, never on the command line (ps shows arguments).
      cat >"$RUN_DIR/redis.conf" <<EOF
bind 127.0.0.1
port $REDIS_PORT
requirepass "$REDIS_PASSWORD"
dir "$DATA_DIR/redis"
appendonly yes
save 60 1000
daemonize no
EOF
      exec redis-server "$RUN_DIR/redis.conf"
      ;;
    web)
      # No system sleep on mains power while the app runs; ends with this PID, even killed.
      caffeinate -s -w $$ >/dev/null 2>&1 &
      export GUNICORN_BIND="127.0.0.1:$WEB_PORT"
      export GUNICORN_WORKERS="${GUNICORN_WORKERS:-$(perf_cores)}"
      exec "$VENV/gunicorn" -c "$ROOT/docker/gunicorn.conf.py" phoresis.wsgi:application
      ;;
    worker)
      local cores
      cores="$(perf_cores)"
      exec "$VENV/celery" -A phoresis_core.celery_app worker --loglevel=info -Q default,heavy \
        --concurrency="${PHORESIS_WORKER_CONCURRENCY:-$((cores > 4 ? cores / 2 : 2))}"
      ;;
    beat)
      exec "$VENV/celery" -A phoresis_core.celery_app beat --loglevel=info --schedule "$RUN_DIR/celerybeat-schedule"
      ;;
    caddy)
      write_caddyfile
      # Its own data folder: this Caddy's local authority and certificates never mix with another app's.
      export XDG_DATA_HOME="$DATA_DIR/caddy" XDG_CONFIG_HOME="$DATA_DIR/caddy/config"
      exec caddy run --config "$RUN_DIR/Caddyfile" --adapter caddyfile
      ;;
    mdns) run_mdns ;;
    nightly) run_nightly ;;
    *) fail "Unknown role: $role" ;;
  esac
}

case "$COMMAND" in
  install) cmd_install "$@" ;;
  uninstall) cmd_uninstall ;;
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_restart ;;
  status) cmd_status ;;
  update) cmd_update "$@" ;;
  logs) cmd_logs "$@" ;;
  backup) cmd_backup ;;
  restore) cmd_restore "$@" ;;
  archive-disk) cmd_archive_disk "$@" ;;
  extra-host) cmd_extra_host "$@" ;;
  shared-caddy) cmd_shared_caddy "$@" ;;
  storage) cmd_manage media_storage "$@" ;;
  manage) cmd_manage "$@" ;;
  trust) cmd_trust ;;
  disk-access) cmd_disk_access ;;
  run) cmd_run "$@" ;;
  -h | --help | help | "") usage ;;
  *) fail "Unknown command: $COMMAND (scripts/mac/phoresis.sh --help)" ;;
esac
