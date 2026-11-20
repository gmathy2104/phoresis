"""
The status workflow of a gel analysis -- the ONE copy of its rules.

Two doors change ``GelAnalysis.status``: the buttons of the analysis page
(``views/api.py::api_analysis_status_transition``, POST ``/gel-analyzer/api/analyses/<pk>/status/``)
and the REST API (``api/views.py::GelAnalysisViewSet.status_transition``, POST
``/gel-analyzer/api/v1/analyses/<pk>/status/``). Until 2026-10-05 the REST door checked only a table
of allowed transitions: any member of ``Full access – gel_analyzer`` could approve or reject an
analysis -- no QA check, no reason, no approver recorded -- and send a completed analysis back to
editing without being its creator. Both doors now call :func:`apply_status_action`, so a rule
changed here changes both, and the QA rung of ``organisation_management/access_catalog.py`` with it
(a rung says what the code does).

THE RULES
---------
=============  ========================  =================================================
action         transition                who may
=============  ========================  =================================================
start          DRAFT → IN_PROGRESS       whoever the door lets in
back_to_draft  IN_PROGRESS → DRAFT       whoever the door lets in
complete       IN_PROGRESS → COMPLETED   the creator
approve        COMPLETED → APPROVED      QA (:func:`user_is_gel_qa`); records who and when
reject         COMPLETED → REJECTED      QA, with a reason
reopen         REJECTED → IN_PROGRESS    the creator; clears the rejection and the approval
recall         COMPLETED → IN_PROGRESS   the creator
=============  ========================  =================================================

The page offers :data:`PAGE_ACTIONS` as buttons (it moves DRAFT → IN_PROGRESS itself when the
editor opens, ``views/analyses.py``). The REST API names a target status and reaches every row
through :data:`ACTION_FOR_TRANSITION`.

QA is staff, or a member of the Gel QA Team -- a group not created in production yet, so today only
staff accounts approve and reject.

WHAT A STATUS LOCKS
-------------------
- DRAFT, IN_PROGRESS: everything is editable (``GelAnalysis.is_editable``).
- COMPLETED, REJECTED: lanes, bands and sample links are locked; densitometry still runs and the
  quantification still saves (a REJECTED analysis publishes nothing: ``signals.py``,
  ``readout_publisher.py``).
- APPROVED: final (owner, 2026-10-05) -- no transition leaves it, and on top no densitometry run and
  no quantification save (:func:`refuse_if_final`). Approving used to lock nothing more than
  COMPLETED: **Run Analysis** replaced the stored values of an approved gel, and **Save & apply**
  its quantification, while the analysis still said *Approved*. To measure the gel again, the user
  creates a new analysis.

The lock lives in the writers -- ``DensitometryService.analyze_and_save`` and
``ProteinQuantCalibrationService.save_active`` -- because a densitometry run is queued before it
writes and the analysis can be approved meanwhile: the writer reads the status under the analysis
row lock, so an approval and a save are ordered, never interleaved. Each door (the densitometry
page's run, the REST ``densitometry/run`` action, the quantification ``POST``/``PATCH``/``DELETE``)
refuses up front with :data:`APPROVED_IS_FINAL` (403) and the page greys both buttons
(:func:`is_final`), so nobody waits for a run that will be refused. Previews, fits and exports write
nothing and stay open.
"""

from __future__ import annotations

from django.utils import timezone

from gel_analyzer.models import GelAnalysis
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)

Status = GelAnalysis.Status

# The group whose members approve and reject, beside staff. Same name as before this module
# existed (views/api.py, views/analyses.py); nothing seeds it, so on a fresh install only staff do.
GEL_QA_TEAM = "Gel QA Team"

PAGE_ACTIONS = ("complete", "approve", "reject", "reopen")

ACTION_FOR_TRANSITION = {
    (Status.DRAFT, Status.IN_PROGRESS): "start",
    (Status.IN_PROGRESS, Status.DRAFT): "back_to_draft",
    (Status.IN_PROGRESS, Status.COMPLETED): "complete",
    (Status.COMPLETED, Status.APPROVED): "approve",
    (Status.COMPLETED, Status.REJECTED): "reject",
    (Status.COMPLETED, Status.IN_PROGRESS): "recall",
    (Status.REJECTED, Status.IN_PROGRESS): "reopen",
}


class StatusChangeRefused(Exception):
    """A refused change. ``str(exc)`` is the message for the user; ``http_status`` is 400 or 403."""

    def __init__(self, message: str, http_status: int = 400):
        super().__init__(message)
        self.http_status = http_status


def user_is_gel_qa(user) -> bool:
    """Staff, or a member of the Gel QA Team: who approves and rejects an analysis."""
    return user.is_staff or user.groups.filter(name=GEL_QA_TEAM).exists()


def _require_status(analysis, expected, message):
    if analysis.status != expected:
        raise StatusChangeRefused(message)


def apply_status_action(analysis: GelAnalysis, action: str, user, reason="") -> None:
    """Apply ``action`` to ``analysis`` for ``user`` and save it, or raise :class:`StatusChangeRefused`.

    The status is checked first (400), then who ``user`` is (403), then the reason (400), so a
    refusal names the first rule broken. ``reason`` counts only for ``reject``; anything but a
    non-blank string is no reason.
    """
    reason = reason.strip() if isinstance(reason, str) else ""
    shown = analysis.get_status_display()
    name = user.get_full_name() or user.username
    is_creator = analysis.created_by_id is not None and analysis.created_by_id == user.pk

    if action == "start":
        _require_status(analysis, Status.DRAFT, f'Cannot start analysis in status "{shown}". Analysis must be Draft.')
        analysis.status = Status.IN_PROGRESS
        analysis._change_reason = f"Started by {name}"
        analysis.save(update_fields=["status", "updated_at"])

    elif action == "back_to_draft":
        _require_status(
            analysis,
            Status.IN_PROGRESS,
            f'Cannot move analysis in status "{shown}" back to Draft. Analysis must be In Progress.',
        )
        analysis.status = Status.DRAFT
        analysis._change_reason = f"Moved back to draft by {name}"
        analysis.save(update_fields=["status", "updated_at"])

    elif action == "complete":
        _require_status(
            analysis,
            Status.IN_PROGRESS,
            f'Cannot complete analysis in status "{shown}". Analysis must be In Progress.',
        )
        if not is_creator:
            raise StatusChangeRefused("Only the analysis creator can mark it as complete.", 403)
        analysis.status = Status.COMPLETED
        analysis._change_reason = f"Marked as completed by {name}"
        analysis.save(update_fields=["status", "updated_at"])

    elif action == "approve":
        _require_status(
            analysis,
            Status.COMPLETED,
            f'Cannot approve analysis in status "{shown}". Analysis must be Completed first.',
        )
        if not user_is_gel_qa(user):
            raise StatusChangeRefused("Only staff or Gel QA Team members can approve analyses.", 403)
        analysis.status = Status.APPROVED
        analysis.approved_by = user
        analysis.approved_at = timezone.now()
        analysis._change_reason = f"Approved by {name}"
        analysis.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])

    elif action == "reject":
        _require_status(
            analysis,
            Status.COMPLETED,
            f'Cannot reject analysis in status "{shown}". Analysis must be Completed first.',
        )
        if not user_is_gel_qa(user):
            raise StatusChangeRefused("Only staff or Gel QA Team members can reject analyses.", 403)
        if not reason:
            raise StatusChangeRefused("A reason is required when rejecting an analysis.")
        analysis.status = Status.REJECTED
        analysis.rejection_reason = reason
        analysis._change_reason = f"Rejected by {name}: {reason}"
        analysis.save(update_fields=["status", "rejection_reason", "updated_at"])

    elif action == "reopen":
        _require_status(
            analysis,
            Status.REJECTED,
            f'Cannot reopen analysis in status "{shown}". Only rejected analyses can be reopened.',
        )
        if not is_creator:
            raise StatusChangeRefused("Only the analysis creator can reopen a rejected analysis.", 403)
        analysis.status = Status.IN_PROGRESS
        analysis.rejection_reason = ""
        analysis.approved_by = None
        analysis.approved_at = None
        analysis._change_reason = f"Reopened by {name}"
        analysis.save(update_fields=["status", "rejection_reason", "approved_by", "approved_at", "updated_at"])

    elif action == "recall":
        _require_status(
            analysis,
            Status.COMPLETED,
            f'Cannot take analysis in status "{shown}" back to In Progress. Analysis must be Completed.',
        )
        if not is_creator:
            raise StatusChangeRefused("Only the analysis creator can take a completed analysis back.", 403)
        analysis.status = Status.IN_PROGRESS
        analysis._change_reason = f"Taken back to In Progress by {name}"
        analysis.save(update_fields=["status", "updated_at"])

    else:
        raise StatusChangeRefused(f"Invalid action: {action}.")

    logger.info(
        f"Analysis status transition: {action}",
        user=user.username,
        analysis_id=str(analysis.pk),
        new_status=analysis.status,
    )


# ---------------------------------------------------------------------------------------------------
# An APPROVED analysis is final (module docstring, WHAT A STATUS LOCKS)
# ---------------------------------------------------------------------------------------------------

APPROVED_IS_FINAL = (
    "This analysis is approved, and an approved analysis is final: its densitometry cannot be re-run "
    "and its quantification cannot be saved. To measure this gel again, create a new analysis."
)


class AnalysisIsFinal(Exception):
    """A writer was asked to change the densitometry or quantification of an approved analysis."""

    def __init__(self, message: str = APPROVED_IS_FINAL):
        super().__init__(message)


def is_final(analysis: GelAnalysis) -> bool:
    """Approved: its densitometry and quantification are locked too, for good."""
    return analysis.status == Status.APPROVED


def refuse_if_final(analysis_pk, *, lock: bool = False) -> None:
    """Raise :class:`AnalysisIsFinal` when the analysis is approved in the database.

    Reads the stored row, never a caller's instance: the one a Celery task holds was loaded before
    the run. ``lock=True`` reads it ``FOR UPDATE`` -- only inside a transaction, the one that writes.
    """
    rows = GelAnalysis.objects.filter(pk=analysis_pk).only("status")
    if lock:
        rows = rows.select_for_update()
    stored = rows.first()
    if stored is not None and is_final(stored):
        raise AnalysisIsFinal()
