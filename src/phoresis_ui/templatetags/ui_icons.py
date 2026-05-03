"""Icon templatetag — renders Lucide and custom Phoresis icons.

Usage:
    {% load ui_icons %}
    {% icon "home" %}                  # 24x24 default
    {% icon "gel" size=20 %}           # custom size
    {% icon "trash-2" class_="text-danger" %}  # extra classes

The Lucide sprite is loaded once per page (via base.html or first {% icon %}
call). Custom icons are inlined per call (small file, simpler than sprite).
"""

from __future__ import annotations

from pathlib import Path

from django import template
from django.contrib.staticfiles.finders import find
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

LUCIDE_SPRITE_REL = "phoresis_ui/icons/lucide.svg"
CUSTOM_ICON_DIR = Path("phoresis_ui/icons/custom")

# Icons that live in the custom directory (everything else is Lucide).
_CUSTOM_NAMES = frozenset(
    {
        "gel",
        "ladder",
        "blot",
        "electrophoresis",
        "densitometry",
        "lane",
        "band",
        "peak",
    }
)


@register.simple_tag
def icon(name: str, size: int = 24, class_: str = "") -> str:
    """Render a single icon (Lucide or custom)."""
    cls = f"inline-block shrink-0 {class_}".strip()
    style = f"width:{size}px;height:{size}px"

    if name in _CUSTOM_NAMES:
        # Inline the custom SVG (small files, no sprite indirection)
        path = find(str(CUSTOM_ICON_DIR / f"{name}.svg"))
        if not path:
            return format_html('<span class="{}">[{}?]</span>', cls, name)
        svg = Path(path).read_text(encoding="utf-8")
        # Inject our class + style into the root <svg>
        svg = svg.replace(
            "<svg ",
            f'<svg class="{cls}" style="{style}" aria-hidden="true" focusable="false" ',
            1,
        )
        return mark_safe(svg)

    # Lucide: <svg><use href="/static/.../lucide.svg#lucide-NAME" /></svg>
    sprite_url = f"/static/{LUCIDE_SPRITE_REL}#lucide-{name}"
    return format_html(
        '<svg class="{}" style="{}" aria-hidden="true" focusable="false"><use href="{}"></use></svg>',
        cls,
        style,
        sprite_url,
    )


@register.simple_tag
def lucide_sprite() -> str:
    """Inject the Lucide sprite once at the top of <body> for downstream <use> refs.

    Optional optimization — works without it, but a single inline sprite avoids
    cross-origin / caching nuances of the external sprite file.
    """
    path = find(LUCIDE_SPRITE_REL)
    if not path:
        return ""
    return mark_safe(Path(path).read_text(encoding="utf-8"))
