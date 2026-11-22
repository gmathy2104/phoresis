"""Celery tasks owned by phoresis_core."""

from __future__ import annotations

from phoresis_core.celery_utils import robust_task


@robust_task(
    soft_time_limit=1800,  # copies to a slow external disk; the pass stops itself after 20 min
    time_limit=2100,
)
def archive_media(self) -> dict:
    """Nightly: move the oldest gel originals to the archive disk when MEDIA_ROOT is over its quota.

    Scheduled only when PHORESIS_MEDIA_ARCHIVE_ROOT is set (settings/base.py). A no-op under quota,
    and when the archive disk is unplugged.
    """
    from phoresis_core.media_tiers import archive_pass

    return archive_pass(time_budget_s=1200)
