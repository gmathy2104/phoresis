"""The tours of Phoresis: every ``<app>/tours/*.json`` of the installed apps, read once at ``ready()``.

A file that breaks a rule of ``tour_schema`` is refused LOUDLY (``logger.error`` names the file and the rules) and
left out -- ``guided_tours/tests/test_tour_files.py`` fails on the same file. Lookups are dict reads.
The dev autoreloader does not watch ``.json``: restart ``runserver`` after editing a tour.
"""

from guided_tours.tour_schema import read_tours
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)

_BY_TEMPLATE = {}
_BY_ID = {}


def load():
    """Fill the registry from the installed apps (``GuidedToursConfig.ready``). Idempotent."""
    from django.apps import apps

    tours, refusals = read_tours(cfg.path for cfg in apps.get_app_configs())
    for path, errors in refusals:
        logger.error(f"guided tours: {path} refused -- {'; '.join(errors)}")
    _BY_TEMPLATE.clear()
    _BY_ID.clear()
    for tour in tours:
        _BY_ID[tour.tour_id] = tour
        for template in tour.templates:
            _BY_TEMPLATE[template] = tour


def tour_for_template(name):
    return _BY_TEMPLATE.get(name) if name else None


def get(tour_id):
    return _BY_ID.get(tour_id)


def all_tours():
    return list(_BY_ID.values())
