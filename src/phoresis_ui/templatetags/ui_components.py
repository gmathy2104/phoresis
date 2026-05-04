"""Phoresis UI component templatetags.

Each tag is a small `inclusion_tag`-style helper that renders a focused
HTML fragment with semantic Tailwind utilities. All variants resolve through
the design tokens in `tokens.css`, so dark mode flips automatically via
`<html data-theme="dark">`.

Conventions:
- Sizes: sm (h-8), md (h-10, default), lg (h-12).
- Variants: primary, secondary, ghost, danger.
- The Alpine.js `toast` and `modal` stores (Task 5) handle dynamic state.
"""

from __future__ import annotations

import json

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


# ============================================================================
# Buttons
# ============================================================================

_BTN_VARIANTS = {
    "primary": "bg-accent-600 text-white hover:bg-accent-700 active:bg-accent-700 focus-visible:outline-accent-500",
    "secondary": "bg-surface text-text border border-border hover:bg-surface-elevated",
    "ghost": "bg-transparent text-text hover:bg-surface-elevated",
    "danger": "bg-danger text-white hover:opacity-90",
}
_BTN_SIZES = {
    "sm": "h-8 px-3 text-sm",
    "md": "h-10 px-4 text-sm",
    "lg": "h-12 px-6 text-base",
}

_BTN_BASE = (
    "inline-flex items-center justify-center gap-2 rounded-md font-medium "
    "transition-colors duration-150 focus-visible:outline focus-visible:outline-2 "
    "focus-visible:outline-offset-2 disabled:opacity-50 disabled:pointer-events-none"
)


@register.simple_tag
def btn(
    label,
    *,
    variant="primary",
    size="md",
    icon=None,
    type_="button",
    href=None,
    hx_post=None,
    hx_target=None,
    class_="",
    disabled=False,
    loading=False,
    extra_attrs="",
):
    """Render a button or anchor styled as a button.

    Examples::
        {% btn "Save" variant="primary" %}
        {% btn "Cancel" variant="ghost" %}
        {% btn "Delete" variant="danger" icon="trash-2" %}
        {% btn "Open" href="/something/" variant="secondary" %}

    `extra_attrs` is a raw HTML attribute fragment passed through unescaped.
    Use it sparingly — typically for Alpine handlers e.g.
    ``extra_attrs='@click="$store.modal.close()"'``.
    Caller is responsible for the safety of `extra_attrs`.
    """
    cls = f"{_BTN_BASE} {_BTN_VARIANTS[variant]} {_BTN_SIZES[size]} {class_}".strip()
    if loading:
        cls += " pointer-events-none"

    icon_html = format_html('<span data-ui-icon="{}"></span>', icon) if icon else ""
    spinner_html = mark_safe('<span class="animate-spin" data-ui-icon="loader"></span>') if loading else ""
    inner = format_html(
        "{}{}<span>{}</span>",
        spinner_html,
        icon_html,
        label,
    )

    htmx_html = ""
    if hx_post:
        htmx_html = format_html(' hx-post="{}"', hx_post)
    if hx_target:
        htmx_html = format_html('{} hx-target="{}"', htmx_html, hx_target)

    # `extra_attrs` is intentionally raw — used for Alpine `@click="…"`-style attrs
    # that contain quotes Django would otherwise escape. Caller-controlled.
    raw_extra = mark_safe(f" {extra_attrs}") if extra_attrs else ""

    if href:
        anchor_extra = ""
        if disabled:
            cls += " pointer-events-none opacity-50"
            anchor_extra = ' aria-disabled="true" tabindex="-1"'
        return format_html(
            '<a href="{}" class="{}"{}{}{}>{}</a>',
            href,
            cls,
            htmx_html,
            raw_extra,
            mark_safe(anchor_extra),
            inner,
        )

    disabled_attr = mark_safe(" disabled") if disabled else ""
    return format_html(
        '<button type="{}" class="{}"{}{}{}>{}</button>',
        type_,
        cls,
        htmx_html,
        raw_extra,
        disabled_attr,
        inner,
    )


# ============================================================================
# Cards
# ============================================================================


@register.inclusion_tag("components/_card.html")
def card(title=None, subtitle=None, hover=True, class_=""):
    """Render a card wrapper (header-only; body uses card_open/card_close)."""
    return {"title": title, "subtitle": subtitle, "hover": hover, "class_": class_}


@register.simple_tag
def card_open(class_="", hover=True):
    hover_cls = "transition-transform duration-150 hover:-translate-y-[2px] hover:shadow-lg" if hover else ""
    return format_html(
        '<div class="rounded-lg border border-border bg-surface p-6 shadow-sm {} {}">',
        mark_safe(hover_cls),
        class_,
    )


@register.simple_tag
def card_close():
    return mark_safe("</div>")


# ============================================================================
# Badges
# ============================================================================

_BADGE_VARIANTS = {
    "default": "bg-surface-elevated text-text border border-border",
    "primary": "bg-accent-50 text-accent-700",
    "success": "bg-success/10 text-success",
    "warning": "bg-warning/10 text-warning",
    "danger": "bg-danger/10 text-danger",
    "info": "bg-info/10 text-info",
    "muted": "bg-surface-elevated text-text-muted border border-border",
    "band": "text-white",  # uses --color-band as bg via inline style
}


@register.simple_tag
def badge(label, *, variant="default", class_=""):
    """Render a small status pill.

    {% badge "DRAFT" variant="warning" %}
    {% badge "SAMPLE" variant="primary" %}
    {% badge "Band" variant="band" %}
    """
    cls = (
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium "
        f"{_BADGE_VARIANTS[variant]} {class_}"
    ).strip()
    if variant == "band":
        return format_html(
            '<span class="{}" style="background-color: var(--color-band);">{}</span>',
            cls,
            label,
        )
    return format_html('<span class="{}">{}</span>', cls, label)


# ============================================================================
# Empty state
# ============================================================================


@register.inclusion_tag("components/_empty_state.html")
def empty_state(title, *, message="", icon="image", cta_label=None, cta_href=None, cta_variant="primary"):
    """Render an empty-state block — illustration + message + optional CTA."""
    return {
        "title": title,
        "message": message,
        "icon": icon,
        "cta_label": cta_label,
        "cta_href": cta_href,
        "cta_variant": cta_variant,
    }


# ============================================================================
# Skeleton (loader)
# ============================================================================


@register.simple_tag
def skeleton(*, height="1rem", width="100%", class_=""):
    """Render a shimmer placeholder."""
    cls = f"ui-shimmer rounded-md {class_}".strip()
    return format_html(
        '<div class="{}" style="width:{};height:{};"></div>',
        cls,
        width,
        height,
    )


# ============================================================================
# Modal (chrome only — body content provided as block in a separate template)
# ============================================================================


@register.inclusion_tag("components/_modal_chrome.html")
def modal_chrome(*, id_, title, size="md"):
    """Render the Alpine-bound modal scaffold. Body goes in the surrounding template."""
    sizes = {"sm": "max-w-md", "md": "max-w-2xl", "lg": "max-w-4xl"}
    return {"id_": id_, "title": title, "size_class": sizes.get(size, sizes["md"])}


# ============================================================================
# Confirm modal — convenience wrapper
# ============================================================================


@register.inclusion_tag("components/_confirm_modal.html")
def confirm(
    *, id_, title, message, confirm_label="Confirm", confirm_variant="danger", cancel_label="Cancel", hx_post=None
):
    return {
        "id_": id_,
        "title": title,
        "message": message,
        "confirm_label": confirm_label,
        "confirm_variant": confirm_variant,
        "cancel_label": cancel_label,
        "hx_post": hx_post,
    }


# ============================================================================
# Toast container — mounts the Alpine `toast` store output
# ============================================================================


@register.inclusion_tag("components/_toast.html")
def toast_container():
    return {}


# ============================================================================
# KPI card (used on dashboard + image list)
# ============================================================================


@register.inclusion_tag("components/_kpi.html")
def kpi(label, value, *, trend=None, trend_label="", icon=None, accent="accent"):
    """Render a single KPI card. `value` should already be the numeric value (CountUp.js animates).

    {% kpi "Total gels" total trend=5 trend_label="vs last week" icon="image" %}
    """
    accents = {
        "accent": "text-accent-600",
        "success": "text-success",
        "warning": "text-warning",
        "danger": "text-danger",
        "info": "text-info",
        "band": "text-band",
    }
    return {
        "label": label,
        "value": value,
        "trend": trend,
        "trend_label": trend_label,
        "icon": icon,
        "accent_class": accents.get(accent, accents["accent"]),
    }


# ============================================================================
# Command palette JSON (Ctrl+K)
# ============================================================================


@register.simple_tag
def nav_palette_items_json() -> str:
    """Serialize ``nav_registry.get_flat_items()`` for the command palette client.

    URLs that look like Django URL names (``app:view``) are reversed; entries
    that fail to reverse are skipped (the URL isn't wired yet — typical during
    progressive Phase 3 build-out).
    """
    from django.urls import NoReverseMatch, reverse

    from phoresis_core.navigation import nav_registry

    items = []
    for item in nav_registry.get_flat_items():
        url = item["url"]
        # Resolve URL name → path if it looks like a name
        if url and ":" in url and "/" not in url:
            try:
                url = reverse(url)
            except NoReverseMatch:
                continue  # URL not yet wired — skip silently
        items.append({"name": item["name"], "url": url, "type": item["type"], "icon": item.get("icon")})
    raw = json.dumps(items)
    # Escape characters that would break out of an inline <script> block
    # (or trigger JS line-separator parsing for U+2028/U+2029).
    raw = (
        raw.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )
    return mark_safe(raw)
