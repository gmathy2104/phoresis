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


# --- components ---


def test_btn_renders_button_element() -> None:
    rendered = Template('{% load ui_components %}{% btn "Save" %}').render(Context({}))
    assert "<button" in rendered and "Save" in rendered
    assert "bg-accent-600" in rendered  # primary variant


def test_btn_with_href_renders_anchor() -> None:
    rendered = Template('{% load ui_components %}{% btn "Open" href="/x/" %}').render(Context({}))
    assert '<a href="/x/"' in rendered


def test_btn_loading_includes_spinner() -> None:
    rendered = Template('{% load ui_components %}{% btn "Save" loading=True %}').render(Context({}))
    assert "animate-spin" in rendered


def test_badge_variants() -> None:
    for variant, expected in [("primary", "text-accent-700"), ("danger", "text-red-700")]:
        rendered = Template(f'{{% load ui_components %}}{{% badge "TEST" variant="{variant}" %}}').render(Context({}))
        assert expected in rendered


def test_skeleton_includes_shimmer_class() -> None:
    rendered = Template("{% load ui_components %}{% skeleton %}").render(Context({}))
    assert "ui-shimmer" in rendered


def test_empty_state_renders_title_and_message() -> None:
    rendered = Template('{% load ui_components %}{% empty_state "No gels" message="Upload one." %}').render(Context({}))
    assert "No gels" in rendered
    assert "Upload one." in rendered


def test_kpi_renders_value_with_countup_attr() -> None:
    rendered = Template('{% load ui_components %}{% kpi "Total" 42 icon="image" %}').render(Context({}))
    assert "Total" in rendered
    assert 'data-countup="42"' in rendered


def test_modal_chrome_renders_close_button() -> None:
    rendered = Template('{% load ui_components %}{% modal_chrome id_="m1" title="Edit" %}').render(Context({}))
    assert "x-show=\"$store.modal.open === 'm1'\"" in rendered
    assert "Edit" in rendered


def test_confirm_renders_buttons() -> None:
    rendered = Template(
        '{% load ui_components %}{% confirm id_="c1" title="Delete?" message="Are you sure?" %}'
    ).render(Context({}))
    assert "Delete?" in rendered
    assert "Are you sure?" in rendered
    assert "Cancel" in rendered  # default cancel_label
