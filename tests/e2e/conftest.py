"""Playwright fixtures for Phoresis e2e tests.

Spawns `runserver` once per session against a dedicated test database, then
seeds an admin user and a primary lab user before each test.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parents[2]
HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server():
    """Start `manage.py runserver` against the test settings, yield the base URL."""
    port = _free_port()
    env = os.environ.copy()
    env["DJANGO_SETTINGS_MODULE"] = "phoresis.settings.test"
    env.setdefault("DB_HOST", "127.0.0.1")
    env.setdefault("DB_USER", "phoresis")
    env.setdefault("DB_PASSWORD", "phoresis")
    env.setdefault("DB_NAME", "phoresis_e2e")
    env["DJANGO_DEBUG"] = "false"

    # Migrate the e2e DB
    subprocess.run(
        [sys.executable, "manage.py", "migrate", "--noinput"],
        cwd=BASE_DIR,
        env=env,
        check=True,
    )

    # Seed admin + primary lab user via the management command
    env_seed = {
        **env,
        "ADMIN_EMAIL": "e2e-admin@phoresis.local",
        "ADMIN_PASSWORD": "e2e-admin-pwd",
        "PRIMARY_USER_EMAIL": "e2e-lab@phoresis.local",
        "PRIMARY_USER_PASSWORD": "e2e-lab-pwd",
        "PRIMARY_USER_FULL_NAME": "E2E Lab",
    }
    subprocess.run(
        [sys.executable, "manage.py", "create_initial_users", "--from-env", "--skip-existing"],
        cwd=BASE_DIR,
        env=env_seed,
        check=True,
    )

    # Start runserver
    proc = subprocess.Popen(
        [sys.executable, "manage.py", "runserver", "--noreload", f"{HOST}:{port}"],
        cwd=BASE_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
    )

    # Wait until it's listening
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with socket.create_connection((HOST, port), timeout=1):
                break
        except OSError:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError("runserver failed to start within 15 seconds")

    yield f"http://{HOST}:{port}"

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def browser_context_args(browser_context_args):
    """Default to a 1280x800 viewport for consistent screenshots."""
    return {**browser_context_args, "viewport": {"width": 1280, "height": 800}}
