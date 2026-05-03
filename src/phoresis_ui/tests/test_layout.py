"""Tests for the layout chrome (sidebar/topbar)."""

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
def test_layout_renders_sidebar_brand(authenticated_request) -> None:
    """Render `_layout.html` directly (as a partial) and confirm sidebar + topbar
    render without crashing, with the brand wordmark and theme toggle present."""
    template = Template("{% include 'components/_layout.html' %}")
    rendered = template.render(RequestContext(authenticated_request))
    # Sidebar brand wordmark
    assert "Phoresis" in rendered
    # Topbar theme toggle
    assert 'aria-label="Light mode"' in rendered
    assert 'aria-label="Dark mode"' in rendered
    # Sidebar nav links use stable hardcoded paths until Task 14 wires URL names
    assert 'href="/images/"' in rendered
    assert 'href="/analyses/"' in rendered
    # Authenticated user → avatar / username block rendered
    assert "layout" in rendered  # username
