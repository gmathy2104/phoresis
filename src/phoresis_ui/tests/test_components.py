"""Tests for phoresis_ui templatetags — icons and components."""

from django.template import Context, Template

# --- icons ---


def test_icon_lucide_renders_use_ref() -> None:
    rendered = Template('{% load ui_icons %}{% icon "home" %}').render(Context({}))
    assert "use href" in rendered or "<use " in rendered
    assert "lucide-home" in rendered


def test_icon_custom_inlines_svg() -> None:
    rendered = Template('{% load ui_icons %}{% icon "gel" %}').render(Context({}))
    # Custom icons are inlined → expect path/line elements, not <use>
    assert "<svg" in rendered
    assert "use href" not in rendered


def test_icon_size_param_overrides_default() -> None:
    rendered = Template('{% load ui_icons %}{% icon "home" size=32 %}').render(Context({}))
    assert "32px" in rendered


def test_icon_class_param_added() -> None:
    rendered = Template('{% load ui_icons %}{% icon "home" class_="text-danger" %}').render(Context({}))
    assert "text-danger" in rendered
