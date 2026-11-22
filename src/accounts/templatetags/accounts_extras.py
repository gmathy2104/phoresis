"""Template helpers for the accounts pages."""

from datetime import timedelta

from django import template

register = template.Library()


@register.filter
def as_minutes(value: timedelta) -> str:
    """A lockout delay in words: '15 minutes', '1 minute'."""
    minutes = max(1, round(value.total_seconds() / 60))
    return f"{minutes} minute{'s' if minutes != 1 else ''}"
