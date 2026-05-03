"""Exception-context capture middleware."""

from __future__ import annotations

import traceback

from django.urls import Resolver404, resolve

from phoresis_core.logging_config import get_logger

from .utils import (
    extract_app_label,
    generate_error_id,
    generate_error_signature,
    get_client_ip,
    sanitize_dict,
)

logger = get_logger(__name__)


class ExceptionContextMiddleware:
    """Capture full request context on unhandled exceptions for ErrorLog.

    Runs early in the stack; stores context on `request._error_context` so
    custom 500 views can render an error reference ID to the user.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request._error_context = None
        return self.get_response(request)

    def process_exception(self, request, exception):
        error_id = generate_error_id()

        view_name = view_func_name = None
        try:
            match = resolve(request.path_info)
            view_name = match.view_name
            view_func_name = getattr(match.func, "__name__", str(match.func))
        except Resolver404:
            view_name = view_func_name = "unknown"
        except Exception:
            pass

        request_data = {}
        try:
            if request.GET:
                request_data["GET"] = sanitize_dict(dict(request.GET))
            if request.POST:
                request_data["POST_keys"] = list(request.POST.keys())
        except Exception:
            pass

        exc_pathname = exc_func_name = exc_lineno = None
        try:
            tb_info = traceback.extract_tb(exception.__traceback__)
            if tb_info:
                last = tb_info[-1]
                exc_pathname, exc_func_name, exc_lineno = last.filename, last.name, last.lineno
        except Exception:
            pass

        exception_type = type(exception).__name__
        error_signature = generate_error_signature(exception_type, exc_pathname, exc_func_name, exc_lineno)
        app_label = extract_app_label(exc_pathname)

        user = request.user if (hasattr(request, "user") and request.user.is_authenticated) else None

        error_context = {
            "error_id": error_id,
            "exception_type": exception_type,
            "exception_message": str(exception),
            "traceback": traceback.format_exc(),
            "http_method": request.method,
            "user_agent": request.META.get("HTTP_USER_AGENT", ""),
            "referer": request.META.get("HTTP_REFERER", ""),
            "client_ip": get_client_ip(request),
            "view_name": view_name,
            "view_func_name": view_func_name,
            "request_data": request_data,
            "user": user,
            "request_path": request.path,
            "error_signature": error_signature,
            "exc_pathname": exc_pathname,
            "exc_func_name": exc_func_name,
            "exc_lineno": exc_lineno,
        }
        request._error_context = error_context

        logger.bind(
            error_id=error_id,
            user=user,
            request_path=request.path,
            http_method=request.method,
            user_agent=error_context["user_agent"],
            referer=error_context["referer"],
            client_ip=error_context["client_ip"],
            view_name=view_name,
            view_func_name=view_func_name,
            request_data=request_data,
            error_signature=error_signature,
            is_handled=False,
            source_type="http",
            app_label=app_label,
        ).exception(f"Unhandled exception [Error ID: {error_id}]: {exception}")

        return None
