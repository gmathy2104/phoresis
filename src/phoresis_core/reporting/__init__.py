"""
Phoresis report-rendering helpers.

The Playwright renderer in ``playwright_renderer`` is intentionally
app-agnostic — it knows about URLs, CSS selectors and PDF/PNG/SVG
output formats, nothing about gels or lanes. The same module is
expected to be reused by the sibling ``django-hub`` project.

The print-token helpers in ``print_token`` provide a one-shot signed
JWT so the headless browser can authenticate against the running web
process without the user having to fish out a session cookie.
"""

from .playwright_renderer import (
    PlaywrightRenderer,
    RenderError,
    render_component,
    render_page_pdf,
)
from .print_token import (
    issue_print_token,
    verify_print_token,
)

__all__ = [
    "PlaywrightRenderer",
    "RenderError",
    "issue_print_token",
    "render_component",
    "render_page_pdf",
    "verify_print_token",
]
