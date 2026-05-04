"""Ladder Template Studio service.

Orchestrates the cross-gel training workflow for a LadderTemplate:
search LADDER lanes across analyses, run top-N-by-intensity auto
assignment, and commit calibrations + training in a single transaction.
"""

from .service import StudioService

__all__ = ["StudioService"]
