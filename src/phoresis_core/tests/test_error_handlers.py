"""Tests for the custom 404 / 500 handler views."""

import pytest


@pytest.mark.django_db
def test_404_returns_branded_page(client) -> None:
    response = client.get("/this-route-does-not-exist-anywhere/")
    assert response.status_code == 404
    assert b"Page not found" in response.content
    assert b"Phoresis" in response.content


@pytest.mark.django_db
def test_500_handler_view_renders_with_error_id(client, rf) -> None:
    """Direct unit test of handler500 — bypass the test client's exception re-raise behavior."""
    from phoresis_core.error_handling.views import handler500

    request = rf.get("/some/failing/path/")
    request._error_context = {"error_id": "PHOR-20260504-ABC123"}
    response = handler500(request)
    response.render()

    assert response.status_code == 500
    assert b"Something broke on our side" in response.content
    assert b"PHOR-20260504-ABC123" in response.content


@pytest.mark.django_db
def test_500_handler_without_error_context(client, rf) -> None:
    """If the middleware didn't set _error_context, the page still renders cleanly."""
    from phoresis_core.error_handling.views import handler500

    request = rf.get("/some/failing/path/")
    response = handler500(request)
    response.render()

    assert response.status_code == 500
    assert b"Something broke on our side" in response.content
    # No reference block should be visible when there's no error_id
    assert b"PHOR-" not in response.content
