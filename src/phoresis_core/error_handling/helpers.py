"""What a handler tells the user when it catches a failure.

Ported from ds-hub-django (``base/error_handling/helpers.py``), keeping the one
function the gel views call. The rule it carries: a caught exception's own text
never reaches the user -- it can name a path, a table or a secret. The user
reads what failed, in the call site's words, and a reference to quote; the
traceback goes to the log under that reference.
"""

from phoresis_core.logging_config import get_logger

from .utils import generate_error_id, get_client_ip


def public_error_text(logger, exc: BaseException, *, public: str, log: str, request=None, level: str = "ERROR") -> str:
    """Log ``exc`` with its traceback under a new error reference and return what the user may read:
    ``public`` (what failed, written by the call site) and the reference -- never the exception's own text.

    ``log`` is the log line; ``request``, when there is one, binds its path, method, user and client IP.
    The record points at the caller (``depth=1``).
    """
    error_id = generate_error_id()
    context = _request_context(request) if request is not None else {}
    if not hasattr(logger, "opt"):  # a stdlib logger: the same name through loguru
        logger = get_logger(logger.name)
    logger.bind(error_id=error_id, is_handled=True, **context).opt(depth=1, exception=exc).log(
        level, f"{log} [Error ID: {error_id}]"
    )
    return f"{public} (reference {error_id})"


def _request_context(request) -> dict:
    user = getattr(request, "user", None)
    return {
        "user": str(user) if user is not None and user.is_authenticated else None,
        "request_path": request.path,
        "http_method": request.method,
        "client_ip": get_client_ip(request),
    }
