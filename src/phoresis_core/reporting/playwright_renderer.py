"""
App-agnostic Playwright renderer for Phoresis (and django-hub) reports.

Loads a URL in headless Chromium and returns:
- ``render_page_pdf(url)``        → PDF bytes (full page).
- ``render_component(url, sel)``  → PNG or SVG bytes for a single DOM
  node (located by CSS selector, e.g. ``#gel-preview``, ``#chart-poi``).

Design notes:

- **No knowledge of gels / analyses / comparisons.** The caller always
  passes a fully-built URL plus an optional CSS selector. This keeps
  the module straight up reusable for django-hub.
- **Browser pool.** Chromium startup is ~400 ms; opening a fresh
  browser per figure is wasteful. We keep a singleton ``Browser``
  per process behind a lock and recycle it. The Celery worker reuses
  the same browser for the duration of a render task; tests teardown
  via :func:`shutdown_renderer`.
- **HTTPS lenient.** In dev/Docker the report site is served by Caddy
  with a self-signed cert at ``https://host.docker.internal`` — the
  context is created with ``ignore_https_errors=True``.
- **SVG mode** uses the page's own SVG.js / Plotly DOM (no rasterising).
  We serialise the matched element's ``outerHTML`` to UTF-8 — works
  for native SVG nodes; for non-SVG nodes we raise ``RenderError``.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Literal

from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


class RenderError(RuntimeError):
    """Raised when Playwright cannot produce the requested artefact."""


# ── Browser singleton ────────────────────────────────────────────────

_lock = threading.Lock()
_renderer: PlaywrightRenderer | None = None


def get_renderer() -> PlaywrightRenderer:
    """Return the process-wide singleton, lazily started."""
    global _renderer
    with _lock:
        if _renderer is None:
            _renderer = PlaywrightRenderer()
            _renderer.start()
        return _renderer


def shutdown_renderer() -> None:
    """Tear down the singleton — call from tests / process exit hooks."""
    global _renderer
    with _lock:
        if _renderer is not None:
            _renderer.stop()
            _renderer = None


# ── Renderer ─────────────────────────────────────────────────────────


class PlaywrightRenderer:
    """Thin wrapper around a long-lived Chromium browser.

    Not thread-safe by itself; the module-level singleton is guarded
    by ``_lock`` and Playwright's own sync API is single-threaded
    (we only ever drive one render at a time per worker process).

    Each call opens a fresh browser context so cookies / auth tokens
    from one render don't bleed into the next.
    """

    def __init__(self) -> None:
        self._pw = None
        self._browser = None

    def start(self) -> None:
        if self._browser is not None:
            return
        from playwright.sync_api import sync_playwright

        logger.info("Starting Playwright + Chromium browser")
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",     # Docker /dev/shm too small
                "--no-sandbox",                 # Chromium in container, root-less ok
                "--disable-gpu",
                "--font-render-hinting=medium",
            ],
        )

    def stop(self) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None

    @contextmanager
    def _new_context(self):
        """One-shot browser context (cookies isolated, ignore self-signed)."""
        if self._browser is None:
            self.start()
        ctx = self._browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1280, "height": 1800},
            device_scale_factor=2,           # crisp on retina + when embedded in PDF
        )
        try:
            yield ctx
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    # ── Public API ────────────────────────────────────────────────

    def render_page_pdf(
        self,
        url: str,
        *,
        wait_selector: str | None = None,
        wait_timeout_ms: int = 15_000,
        prefer_css_page_size: bool = True,
        format: str = "A4",
        landscape: bool = False,
        margin: dict | None = None,
    ) -> bytes:
        """Open ``url`` in headless Chromium and return a PDF.

        Args:
            url: full URL (must be reachable from the worker; e.g.
                ``https://host.docker.internal/analyses/<id>/report/print/?token=…``).
            wait_selector: optional CSS selector to wait for before
                printing — useful when the page has async charts
                (Plotly is rendered in ``window.requestAnimationFrame``).
            wait_timeout_ms: bound for ``wait_for_selector``.
            prefer_css_page_size: respect ``@page size`` in the page's
                stylesheet if present.
            format: PDF page format ("A4", "Letter", …).
            landscape: page orientation.
            margin: dict of margins, e.g. ``{"top": "1cm", "bottom": "1cm",
                "left": "0.5cm", "right": "0.5cm"}``.
        """
        with self._new_context() as ctx:
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=30_000)
                if wait_selector:
                    page.wait_for_selector(wait_selector, timeout=wait_timeout_ms)
                pdf_bytes = page.pdf(
                    format=format,
                    landscape=landscape,
                    margin=margin or {"top": "1cm", "bottom": "1cm", "left": "1cm", "right": "1cm"},
                    prefer_css_page_size=prefer_css_page_size,
                    print_background=True,
                )
                return pdf_bytes
            except Exception as exc:
                raise RenderError(f"PDF render failed for {url}: {exc}") from exc
            finally:
                page.close()

    def render_component(
        self,
        url: str,
        selector: str,
        *,
        out_format: Literal["png", "svg"] = "png",
        wait_selector: str | None = None,
        wait_timeout_ms: int = 15_000,
        omit_background: bool = False,
    ) -> bytes:
        """Render a single DOM node from ``url`` (matched by ``selector``).

        - ``out_format="png"`` → screenshot of the bounding box (highest
          fidelity, scales fine in DOCX/PPTX at the device_scale_factor=2
          we set on the context).
        - ``out_format="svg"`` → ``element.outerHTML`` as UTF-8 bytes;
          only works when the matched element is itself an ``<svg>``.

        Args:
            url: page URL containing the component.
            selector: CSS selector for the component (e.g.
                ``"#gel-preview svg"``, ``".js-poi-purity-chart"``).
            out_format: ``"png"`` (default) or ``"svg"``.
            wait_selector: optional extra selector to wait for before
                snapshotting (defaults to ``selector``).
            wait_timeout_ms: ``wait_for_selector`` timeout.
            omit_background: PNG-only — transparent background.
        """
        if out_format not in ("png", "svg"):
            raise ValueError(f"unsupported out_format: {out_format!r}")

        with self._new_context() as ctx:
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=30_000)
                page.wait_for_selector(wait_selector or selector, timeout=wait_timeout_ms)
                handle = page.query_selector(selector)
                if handle is None:
                    raise RenderError(
                        f"selector {selector!r} not found on {url}"
                    )
                if out_format == "png":
                    return handle.screenshot(omit_background=omit_background, type="png")
                # SVG path
                tag = handle.evaluate("el => el.tagName.toLowerCase()")
                if tag != "svg":
                    raise RenderError(
                        f"selector {selector!r} matched a <{tag}>, but svg export requires an <svg> element"
                    )
                outer = handle.evaluate("el => el.outerHTML")
                return outer.encode("utf-8")
            except RenderError:
                raise
            except Exception as exc:
                raise RenderError(
                    f"component render failed for {url} ({selector!r}): {exc}"
                ) from exc
            finally:
                page.close()


# ── Convenience module-level helpers ─────────────────────────────────


def render_page_pdf(url: str, **kwargs) -> bytes:
    """Module-level shortcut that uses the singleton renderer."""
    return get_renderer().render_page_pdf(url, **kwargs)


def render_component(url: str, selector: str, **kwargs) -> bytes:
    """Module-level shortcut that uses the singleton renderer."""
    return get_renderer().render_component(url, selector, **kwargs)
