"""Gunicorn config for the Phoresis web container."""

import multiprocessing  # noqa: F401  (kept for reference; can be used to derive workers from cpu_count)
import os

from gunicorn.glogging import Logger

# Bind to the internal port; Caddy proxies in.
bind = f"0.0.0.0:{os.environ.get('GUNICORN_PORT', '8000')}"

# 4 sync workers per spec §5.1; can be tuned via env.
workers = int(os.environ.get("GUNICORN_WORKERS", "4"))
worker_class = "sync"
threads = int(os.environ.get("GUNICORN_THREADS", "2"))

# Timeout — gel image processing on upload can take ~10s on big files; default 30s is tight.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 5

# Logging — to stdout/stderr so Docker captures (loguru's InterceptHandler keeps the format consistent).
accesslog = "-"
errorlog = "-"
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)ss'


# Healthcheck access-log filter.
#
# Caddy probes /healthz/live/ every 10s + Docker container healthcheck probes
# every 30s = ~500 noise lines per hour drowning real signal in the web logs.
# Subclass gunicorn's Logger to drop access entries for any /healthz/* request,
# while preserving normal access logging for everything else and ALL error
# logging (errors on /healthz/ would still surface via the error log channel).
#
# Pattern documented in gunicorn issues #1078 and #1494; this is the canonical
# way to filter access logs without breaking the rest of the logging stack.
class _FilteredAccessLogger(Logger):
    def access(self, resp, req, environ, request_time):
        path = environ.get("PATH_INFO", "")
        if path.startswith("/healthz/"):
            return
        super().access(resp, req, environ, request_time)


logger_class = _FilteredAccessLogger

# Reload disabled in production.
reload = False

# Preload reduces per-worker memory by sharing the import graph (loguru, torch, etc.).
preload_app = True
