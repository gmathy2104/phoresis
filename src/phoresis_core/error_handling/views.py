"""Error handler views for 404 / 500."""

from django.template.response import TemplateResponse


def handler404(request, exception):
    """Custom 404 - branded, no error ID needed."""
    return TemplateResponse(request, "404.html", {"path": request.path}, status=404)


def handler500(request):
    """Custom 500 - surfaces the error_id from ExceptionContextMiddleware."""
    ctx = getattr(request, "_error_context", None) or {}
    return TemplateResponse(
        request,
        "500.html",
        {"error_id": ctx.get("error_id"), "path": request.path},
        status=500,
    )
