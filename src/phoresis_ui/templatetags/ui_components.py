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

from django import template
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
):
    """Render a button or anchor styled as a button.

    Examples::
        {% btn "Save" variant="primary" %}
        {% btn "Cancel" variant="ghost" %}
        {% btn "Delete" variant="danger" icon="trash-2" %}
        {% btn "Open" href="/something/" variant="secondary" %}
    """
    base = "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50 disabled:pointer-events-none"
    cls = f"{base} {_BTN_VARIANTS[variant]} {_BTN_SIZES[size]} {class_}".strip()

    icon_html = ""
    if icon:
        icon_html = f'<span data-ui-icon="{icon}"></span>'

    spinner = ""
    if loading:
        spinner = '<span class="animate-spin" data-ui-icon="loader"></span>'
        cls += " pointer-events-none"

    inner = f"{spinner}{icon_html}<span>{label}</span>"

    htmx_attrs = ""
    if hx_post:
        htmx_attrs += f' hx-post="{hx_post}"'
    if hx_target:
        htmx_attrs += f' hx-target="{hx_target}"'

    if href:
        return mark_safe(f'<a href="{href}" class="{cls}"{htmx_attrs}>{inner}</a>')

    disabled_attr = " disabled" if disabled else ""
    return mark_safe(f'<button type="{type_}" class="{cls}"{htmx_attrs}{disabled_attr}>{inner}</button>')


# ============================================================================
# Cards
# ============================================================================


@register.inclusion_tag("components/_card.html")
def card(title=None, subtitle=None, hover=True, class_=""):
    """Render a card wrapper (header-only — body content uses card_open/card_close)."""
    return {"title": title, "subtitle": subtitle, "hover": hover, "class_": class_}


# Card body block — Django templates don't have block-form simple_tag, so we provide
# raw fragments via two helpers:


@register.simple_tag
def card_open(class_="", hover=True):
    hover_cls = "transition-transform duration-150 hover:-translate-y-[2px] hover:shadow-lg" if hover else ""
    return mark_safe(f'<div class="rounded-lg border border-border bg-surface p-6 shadow-sm {hover_cls} {class_}">')


@register.simple_tag
def card_close():
    return mark_safe("</div>")


# ============================================================================
# Badges
# ============================================================================

_BADGE_VARIANTS = {
    "default": "bg-surface-elevated text-text border border-border",
    "primary": "bg-accent-50 text-accent-700",
    "success": "bg-emerald-50 text-emerald-700",
    "warning": "bg-amber-50 text-amber-700",
    "danger": "bg-red-50 text-red-700",
    "info": "bg-cyan-50 text-cyan-700",
    "muted": "bg-zinc-100 text-zinc-700",
    "band": "text-white",  # uses --color-band as bg via inline style
}


@register.simple_tag
def badge(label, *, variant="default", class_=""):
    """Render a small status pill.

    {% badge "DRAFT" variant="warning" %}
    {% badge "SAMPLE" variant="primary" %}
    {% badge "Band" variant="band" %}
    """
    cls = f"inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium {_BADGE_VARIANTS[variant]} {class_}".strip()
    style = ' style="background-color: var(--color-band);"' if variant == "band" else ""
    return mark_safe(f'<span class="{cls}"{style}>{label}</span>')


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
    return mark_safe(f'<div class="{cls}" style="width:{width};height:{height};"></div>')


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
    *,
    id_,
    title,
    message,
    confirm_label="Confirm",
    confirm_variant="danger",
    cancel_label="Cancel",
    hx_post=None,
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
