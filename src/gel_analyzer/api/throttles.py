"""
Custom throttle classes for Gel Analyzer API.
"""

from rest_framework.throttling import UserRateThrottle


class WriteRateThrottle(UserRateThrottle):
    """Throttle for create/update/delete operations."""

    scope = "user_write"


class ComputationRateThrottle(UserRateThrottle):
    """Throttle for expensive computation triggers (detection, densitometry)."""

    scope = "user_computation"
