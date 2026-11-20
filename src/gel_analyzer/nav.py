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
        {"name": "Comparisons", "url": "gel_analyzer:comparison_list", "icon": "grid-2x2"},
    ],
    actions=[
        {"name": "Upload gel", "url": "gel_analyzer:image_upload", "icon": "upload"},
    ],
)

# The gel IMAGE is the thing people look for -- a filename carrying a sheet or a
# batch number, typed into Ctrl+K to find out whether that gel exists. Its page
# links to its own analyses from there.
#
# Deliberately NOT registered beside it:
# * `GelAnalysis`: its `name` is blank on almost every row, so five analyses of
#   one gel would arrive as five rows all titled the same filename.
# * `GelAssay`: a catalogue of readout types ("what this gel is read for"), not
#   a lab artefact, and its only URL is the edit form.
nav_registry.register_searchable(
    app_label="gel_analyzer",
    models=[
        {
            "model": "GelImage",
            # `description` is here on purpose: a batch or sheet number is often
            # typed into it rather than into the filename.
            "search_fields": ["original_filename", "description"],
            "display_field": "original_filename",
            # The gel TYPE is what tells two gels of the same batch apart, and
            # it always has a value (default UNKNOWN -> "Unknown"), so this
            # template never leaves a separator dangling.
            "subtitle_template": "{get_gel_type_display}",
            "label": "Gel images",
            "url_pattern": "gel_analyzer:image_detail",
        },
    ],
)
