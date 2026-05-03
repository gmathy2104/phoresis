"""Register the Gel Analyzer app in the navigation registry."""

from phoresis_core.navigation import nav_registry

nav_registry.register_app(
    app_label="gel_analyzer",
    display_name="Gel Analyzer",
    group="Lab Tools",
    icon="image",
    keywords=["gel", "SDS-PAGE", "dot blot", "western blot", "band", "densitometry", "electrophoresis"],
    shortcut_key="g",
    pages=[
        {"name": "Gel images", "url": "gel_analyzer:image_list", "icon": "image"},
        {"name": "Analyses", "url": "gel_analyzer:analysis_list", "icon": "layers"},
    ],
    actions=[
        {"name": "Upload gel", "url": "gel_analyzer:image_upload", "icon": "upload"},
    ],
)
