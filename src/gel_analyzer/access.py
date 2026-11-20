"""Who may read and modify gel data -- the ONE copy of the rule.

Ported from ds-hub-django, where writing is reserved to an access group handed
out per application. Phoresis is a single-lab install with no such catalogue:
every signed-in account reads AND writes, as it did before this module existed.
The functions keep their hub names so the views and the API ported from the hub
call them unchanged; tightening the rule later (for instance to
``accounts.permissions.is_lab_user``) is a change to
:func:`user_can_write_gel_analyzer` alone.

A SAVED COMPARISON IS ITS CREATOR'S
-----------------------------------
Unlike gels, a saved comparison is personal: only its creator modifies or
deletes it, and another account sees it only when it is public. An orphan
(``created_by`` NULL once its creator was deleted) belongs to nobody.

This module imports no model: it is imported while the app registry loads.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

__all__ = [
    "user_can_read_gel_analyzer",
    "user_can_write_gel_analyzer",
    "user_owns_saved_comparison",
    "user_can_read_saved_comparison",
    "saved_comparisons_readable_by",
    "IsGelAnalyzerUser",
    "IsSavedComparisonOwnerOrReadOnly",
]


def user_can_read_gel_analyzer(user) -> bool:
    """Any signed-in account. ``is_authenticated`` only: ``request.user`` is a lazy wrapper."""
    return bool(user and user.is_authenticated)


def user_can_write_gel_analyzer(user) -> bool:
    """Any signed-in account (module docstring): the one place to tighten the write rule."""
    return bool(user and user.is_authenticated)


def user_owns_saved_comparison(user, comparison) -> bool:
    """The creator of ``comparison``: the only account that may modify or delete it.

    Compares ids, so it costs no query, and an orphan belongs to nobody -- the
    anonymous user, whose pk is None, included.
    """
    if not user or not user.is_authenticated:
        return False
    return comparison.created_by_id is not None and comparison.created_by_id == user.pk


def user_can_read_saved_comparison(user, comparison) -> bool:
    """Public, or the caller's own."""
    if not user or not user.is_authenticated:
        return False
    return comparison.is_public or user_owns_saved_comparison(user, comparison)


def saved_comparisons_readable_by(user, queryset):
    """``queryset`` narrowed, in SQL, to the comparisons ``user_can_read_saved_comparison`` admits.

    Takes the caller's queryset rather than building one: each caller keeps its own
    ``select_related`` and ordering, and this module stays free of model imports.
    """
    if not user or not user.is_authenticated:
        return queryset.none()
    from django.db.models import Q

    return queryset.filter(Q(is_public=True) | Q(created_by_id=user.pk))


class IsGelAnalyzerUser(BasePermission):
    """DRF gate: read = any signed-in account, write = :func:`user_can_write_gel_analyzer`."""

    message = "You are not allowed to modify gel data."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return user_can_write_gel_analyzer(request.user)


class IsSavedComparisonOwnerOrReadOnly(BasePermission):
    """DRF object gate for ``SavedComparison``: read = creator or public, write = creator.

    Comes after ``IsGelAnalyzerUser`` and beside a ``get_queryset`` narrowed by
    ``saved_comparisons_readable_by``: that narrowing is what turns another account's
    private comparison into a 404; what is left for this class is the 403 on a public
    comparison that is not the caller's.
    """

    message = "Only the creator of this comparison may modify or delete it."

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return user_can_read_saved_comparison(request.user, obj)
        return user_owns_saved_comparison(request.user, obj)
