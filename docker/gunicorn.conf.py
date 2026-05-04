"""Gunicorn config for the Phoresis web container."""

import multiprocessing  # noqa: F401  (kept for reference; can be used to derive workers from cpu_count)
import os

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

# Reload disabled in production.
reload = False

# Preload reduces per-worker memory by sharing the import graph (loguru, torch, etc.).
preload_app = True
