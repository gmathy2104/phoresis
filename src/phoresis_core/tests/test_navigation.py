"""Tests for phoresis_core.navigation."""

import pytest

from phoresis_core.navigation import NavRegistry, nav_registry


@pytest.fixture
def fresh_registry():
    """Provide an isolated NavRegistry per test."""
    yield NavRegistry()


def test_register_app_stores_minimal_entry(fresh_registry: NavRegistry) -> None:
    fresh_registry.register_app(
        app_label="acc",
        display_name="Accounts",
        group="Management",
        icon="user",
        pages=[{"name": "Profile", "url": "/accounts/profile/"}],
    )
    apps = fresh_registry.get_apps()
    assert "acc" in apps
    assert apps["acc"]["display_name"] == "Accounts"
    assert apps["acc"]["pages"][0]["name"] == "Profile"


def test_register_app_rejects_duplicate_label(fresh_registry: NavRegistry) -> None:
    fresh_registry.register_app(app_label="x", display_name="X", group="Lab Tools", icon="i", pages=[])
    with pytest.raises(ValueError, match="already registered"):
        fresh_registry.register_app(app_label="x", display_name="X2", group="Lab Tools", icon="i", pages=[])


def test_get_groups_returns_all_canonical_groups_even_when_empty(fresh_registry: NavRegistry) -> None:
    groups = fresh_registry.get_groups()
    assert set(groups.keys()) == {"Research", "Analytics & Data", "Management", "Lab Tools"}
    assert all(g["apps"] == [] for g in groups.values())


def test_get_flat_items_yields_pages_and_actions(fresh_registry: NavRegistry) -> None:
    fresh_registry.register_app(
        app_label="x",
        display_name="X",
        group="Lab Tools",
        icon="i",
        pages=[{"name": "Home", "url": "/x/"}],
        actions=[{"name": "New X", "url": "/x/new/"}],
    )
    items = fresh_registry.get_flat_items()
    assert any(i["name"] == "X — Home" and i["type"] == "page" for i in items)
    assert any(i["name"] == "New X" and i["type"] == "action" for i in items)


def test_module_singleton_is_a_NavRegistry() -> None:
    assert isinstance(nav_registry, NavRegistry)
