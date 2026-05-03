"""Register the Gel Analyzer app in the navigation registry.

Pages and actions are added in Phase 3 once the views exist.
"""

from phoresis_core.navigation import nav_registry

nav_registry.register_app(
    app_label="gel_analyzer",
    display_name="Gel Analyzer",
    group="Lab Tools",
    icon="image",
    keywords=["gel", "SDS-PAGE", "dot blot", "band", "densitometry", "electrophoresis", "western blot"],
    shortcut_key="g",
    pages=[],  # filled in Phase 3
    actions=[],  # filled in Phase 3
)
