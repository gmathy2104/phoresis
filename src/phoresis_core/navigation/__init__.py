"""NavRegistry — central navigation singleton for Phoresis.

Apps register themselves via `nav.py` files at app-ready time. The registry
feeds the command palette (Ctrl+K), the sidebar, and the keyboard shortcuts.

Usage::

    from phoresis_core.navigation import nav_registry

    nav_registry.register_app(
        app_label="gel_analyzer",
        display_name="Gel Analyzer",
        group="Lab Tools",
        icon="image",
        url="/gel-analyzer/",
        pages=[{"name": "Upload", "url": "/gel-analyzer/upload/", "icon": "upload"}],
        actions=[{"name": "New Analysis", "url": "/gel-analyzer/new/", "icon": "plus"}],
        shortcut_key="g",
    )
"""

from __future__ import annotations

from typing import Any


class NavRegistry:
    """Singleton-style registry for Phoresis navigation."""

    GROUP_DEFINITIONS: dict[str, dict[str, str]] = {
        "Lab Tools": {"color": "#3b82f6", "icon": "wrench"},
        "Research": {"color": "#a855f7", "icon": "flask-conical"},
        "Analytics & Data": {"color": "#22c55e", "icon": "trending-up"},
        "Management": {"color": "#f59e0b", "icon": "kanban"},
    }
    GROUP_ORDER: list[str] = ["Research", "Analytics & Data", "Management", "Lab Tools"]

    def __init__(self) -> None:
        self._apps: dict[str, dict[str, Any]] = {}
        self._searchables: dict[str, list[dict[str, Any]]] = {}

    def register_app(
        self,
        *,
        app_label: str,
        display_name: str,
        group: str,
        icon: str,
        url: str | None = None,
        pages: list[dict[str, Any]],
        actions: list[dict[str, Any]] | None = None,
        shortcut_key: str | None = None,
        keywords: list[str] | None = None,
        permission: str | None = None,
    ) -> None:
        if app_label in self._apps:
            raise ValueError(
                f"NavRegistry: app_label '{app_label}' is already registered. " "Each app_label must be unique."
            )
        self._apps[app_label] = {
            "app_label": app_label,
            "display_name": display_name,
            "group": group,
            "icon": icon,
            "url": url,
            "pages": pages,
            "actions": actions or [],
            "shortcut_key": shortcut_key.upper() if shortcut_key else "",
            "keywords": keywords or [],
            "permission": permission,
        }

    def register_searchable(self, *, app_label: str, models: list[dict[str, Any]]) -> None:
        self._searchables.setdefault(app_label, []).extend(models)

    def get_apps(self) -> dict[str, dict[str, Any]]:
        return dict(self._apps)

    def get_groups(self) -> dict[str, dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for name in self.GROUP_ORDER:
            defn = self.GROUP_DEFINITIONS[name]
            groups[name] = {"color": defn["color"], "icon": defn["icon"], "apps": []}
        for app in self._apps.values():
            if app["group"] in groups:
                groups[app["group"]]["apps"].append(app)
        return groups

    def get_flat_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for app in self._apps.values():
            label, display, group = app["app_label"], app["display_name"], app["group"]
            for page in app.get("pages", []):
                items.append(
                    {
                        "name": f"{display} — {page['name']}",
                        "url": page["url"],
                        "type": "page",
                        "icon": page.get("icon", app["icon"]),
                        "app_label": label,
                        "group": group,
                        "keywords": page.get("keywords", []),
                    }
                )
            for action in app.get("actions", []):
                items.append(
                    {
                        "name": action["name"],
                        "url": action["url"],
                        "type": "action",
                        "icon": action.get("icon", app["icon"]),
                        "app_label": label,
                        "group": group,
                        "keywords": action.get("keywords", []),
                    }
                )
        return items

    def get_searchables(self) -> dict[str, list[dict[str, Any]]]:
        return dict(self._searchables)

    def clear(self) -> None:
        self._apps.clear()
        self._searchables.clear()


nav_registry = NavRegistry()
