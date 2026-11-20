"""The band model the annotation editor runs in the browser (``settings.GEL_ANALYZER_BAND_MODEL``).

One place reads its configuration and proves that the shipped file is the configured one: the system check
(``gel_analyzer/checks.py``, so ``manage.py check`` and preflight check 1 before every push) and the endpoints that
hand the model to the browser. A configuration that does not hold together is refused with what is wrong, never
patched up: a browser running another file than the one named here would write bands nobody can trace.
"""

from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path

from django.conf import settings

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STRIDE = 32  # YOLO's largest stride: an input side must be a multiple of it


class BandModelUnavailable(Exception):
    """The configured band model cannot be served as configured."""


def band_model_config() -> dict:
    """``settings.GEL_ANALYZER_BAND_MODEL``, checked key by key; every problem is named at once."""
    raw = getattr(settings, "GEL_ANALYZER_BAND_MODEL", None)
    if not isinstance(raw, dict):
        raise BandModelUnavailable("settings.GEL_ANALYZER_BAND_MODEL is missing or not a dict")
    problems = []
    for key in ("name", "static_path"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            problems.append(f"{key} must be a non-empty string")
    for key in ("sha256", "source_sha256"):
        if not isinstance(raw.get(key), str) or not _SHA256.match(raw[key]):
            problems.append(f"{key} must be 64 lowercase hex characters")
    names = raw.get("class_names")
    if not isinstance(names, list) or not names or not all(isinstance(n, str) and n for n in names):
        problems.append("class_names must be a non-empty list of names")
    imgsz = raw.get("imgsz")
    if not _is_int(imgsz) or imgsz <= 0 or imgsz % _STRIDE:
        problems.append(f"imgsz must be a positive multiple of {_STRIDE}")
    for key in ("confidence", "min_confidence", "iou"):
        value = raw.get(key)
        if not _is_number(value) or not 0 < value < 1:
            problems.append(f"{key} must be a number strictly between 0 and 1")
    if (
        _is_number(raw.get("confidence"))
        and _is_number(raw.get("min_confidence"))
        and raw["min_confidence"] > raw["confidence"]
    ):
        problems.append("min_confidence (the slider's floor) must not exceed confidence (its default)")
    max_det = raw.get("max_det")
    if not _is_int(max_det) or max_det < 1:
        problems.append("max_det must be a positive integer")
    if problems:
        raise BandModelUnavailable("settings.GEL_ANALYZER_BAND_MODEL: " + "; ".join(problems))
    return dict(raw)


def band_model_path(config: dict) -> Path:
    """The file behind ``static_path``, found the way ``{% static %}`` serves it in development."""
    from django.contrib.staticfiles import finders  # noqa: PLC0415 -- the app registry must be ready

    found = finders.find(config["static_path"])
    if not found:
        raise BandModelUnavailable(f"{config['static_path']} is in no static directory")
    return Path(found)


_digests: dict[tuple, str] = {}
_digests_lock = threading.Lock()


def file_sha256(path: Path) -> str:
    """sha256 of ``path``, cached on (path, size, mtime): runserver re-runs the system checks at every reload."""
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    with _digests_lock:
        cached = _digests.get(key)
    if cached is not None:
        return cached
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    with _digests_lock:
        _digests[key] = value
    return value


def verified_band_model() -> dict:
    """The configuration, once its file is proved to be the configured one; raises :class:`BandModelUnavailable`."""
    config = band_model_config()
    path = band_model_path(config)
    actual = file_sha256(path)
    if actual != config["sha256"]:
        raise BandModelUnavailable(
            f"{path} has sha256 {actual} but settings.GEL_ANALYZER_BAND_MODEL expects {config['sha256']}: "
            "re-export with scripts/export_gel_band_model.py and copy the sha256 it prints, or restore the file"
        )
    return config


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
