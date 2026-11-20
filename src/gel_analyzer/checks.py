"""System checks of gel_analyzer, registered in ``GelAnalyzerConfig.ready()``.

``manage.py check`` runs them, and so do ``migrate`` and ``runserver``.
"""

from django.core import checks

LFS_POINTER_PREFIX = b"version https://git-lfs"


def _is_lfs_pointer(path) -> bool:
    """A clone without git-lfs leaves a ~134-byte text pointer where the model should be (AGENTS.md §4)."""
    try:
        if path.stat().st_size > 1024:
            return False
        with open(path, "rb") as handle:
            return handle.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX
    except OSError:
        return False


@checks.register()
def band_model_check(app_configs, **kwargs):
    """The band model file the editor will run is the one ``settings.GEL_ANALYZER_BAND_MODEL`` names.

    An Error, so a wrong or re-exported file is never served unnoticed -- except when the file is a
    Git LFS pointer: the CI jobs that only lint and test clone without LFS on purpose, and an Error
    would stop their ``migrate``. That case is a Warning; the editor's band detection answers 503
    there (``views/band_model_api.py``), and ``install.ps1`` refuses to deploy such a clone.
    """
    if app_configs is not None and not any(config.name == "gel_analyzer" for config in app_configs):
        return []
    from gel_analyzer.services.band_model import (  # noqa: PLC0415
        BandModelUnavailable,
        band_model_config,
        band_model_path,
        verified_band_model,
    )

    try:
        verified_band_model()
    except BandModelUnavailable as exc:
        try:
            pointer = _is_lfs_pointer(band_model_path(band_model_config()))
        except BandModelUnavailable:
            pointer = False
        if pointer:
            return [
                checks.Warning(
                    "The band model is a Git LFS pointer, not the model: band detection is unavailable.",
                    hint="Install git-lfs and run `git lfs pull`.",
                    id="gel_analyzer.W001",
                )
            ]
        return [
            checks.Error(
                str(exc),
                hint="The annotation editor would run a band model nobody can trace. Restore the file shipped "
                "with this version, or update settings.GEL_ANALYZER_BAND_MODEL with the new file's sha256.",
                id="gel_analyzer.E001",
            )
        ]
    return []
