"""Tests for the phoresis_ui templatetag scaffolding."""

from django.template import Context, Template


def test_ui_components_load_without_error() -> None:
    Template("{% load ui_components %}").render(Context({}))


def test_ui_icons_load_without_error() -> None:
    Template("{% load ui_icons %}").render(Context({}))


def test_base_template_extends_render() -> None:
    template = Template("{% extends 'components/base.html' %}{% block content %}HELLO{% endblock %}")
    rendered = template.render(Context({}))
    assert "HELLO" in rendered
    assert "Phoresis" in rendered
