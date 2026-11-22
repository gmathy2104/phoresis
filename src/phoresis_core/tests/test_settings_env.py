"""Settings read from the environment (phoresis.settings.base)."""

import importlib

import pytest


@pytest.fixture
def base_with_env(monkeypatch):
    """phoresis.settings.base re-read under a given environment, and put back afterwards."""
    from phoresis.settings import base

    def load(**env):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return importlib.reload(base)

    yield load
    monkeypatch.undo()
    importlib.reload(base)


def test_redis_urls_carry_no_credentials_by_default(base_with_env, monkeypatch):
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    base = base_with_env(REDIS_HOST="redis", REDIS_PORT="6379")
    assert base.CELERY_BROKER_URL == "redis://redis:6379/0"


def test_redis_password_is_quoted_into_every_url(base_with_env):
    base = base_with_env(REDIS_HOST="127.0.0.1", REDIS_PORT="6390", REDIS_PASSWORD="p@ss/w:rd")
    assert base.CELERY_BROKER_URL == "redis://:p%40ss%2Fw%3Ard@127.0.0.1:6390/0"
    assert base.CACHES["default"]["LOCATION"] == "redis://:p%40ss%2Fw%3Ard@127.0.0.1:6390/1"


def test_archive_root_switches_the_storage_and_schedules_the_nightly_pass(base_with_env, monkeypatch):
    monkeypatch.delenv("PHORESIS_MEDIA_ARCHIVE_ROOT", raising=False)
    base = base_with_env()
    assert base.STORAGES["default"]["BACKEND"] == "django.core.files.storage.FileSystemStorage"
    assert "archive-media-nightly" not in base.CELERY_BEAT_SCHEDULE

    base = base_with_env(PHORESIS_MEDIA_ARCHIVE_ROOT="/Volumes/Disk/Phoresis/media", PHORESIS_MEDIA_HOT_QUOTA_GB="2.5")
    assert base.STORAGES["default"]["BACKEND"] == "phoresis_core.media_tiers.TieredMediaStorage"
    assert base.CELERY_BEAT_SCHEDULE["archive-media-nightly"]["task"] == "phoresis_core.tasks.archive_media"
    assert int(2.5 * 1024**3) == base.PHORESIS_MEDIA_HOT_QUOTA_BYTES
