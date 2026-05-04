"""Tests for the layout chrome (sidebar/topbar/palette/toast in app_base.html)."""

import pytest

from django.template import RequestContext, Template
from django.test import RequestFactory


@pytest.fixture
def authenticated_request(db, django_user_model):
    user = django_user_model.objects.create_user(username="layout", password="x")
    rf = RequestFactory()
    req = rf.get("/")
    req.user = user
    req.resolver_match = type("RM", (), {"namespace": "dashboard", "url_name": "home"})()
    return req


@pytest.mark.django_db
def test_app_base_renders_chrome(authenticated_request) -> None:
    """app_base.html provides sidebar + topbar + content slot for authenticated pages."""
    template = Template("{% extends 'components/app_base.html' %}{% block content %}HELLO{% endblock %}")
    rendered = template.render(RequestContext(authenticated_request))
    assert "Phoresis" in rendered  # sidebar brand
    assert 'aria-label="Light mode"' in rendered  # theme toggle present
    assert 'aria-label="Dark mode"' in rendered
    assert "HELLO" in rendered  # content block actually renders
