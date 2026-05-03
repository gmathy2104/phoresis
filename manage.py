#!/usr/bin/env python
"""Django administrative tasks — adds src/ to sys.path before delegating."""

import os
import sys
from pathlib import Path


def main() -> None:
    src_dir = Path(__file__).resolve().parent / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "phoresis.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError("Couldn't import Django. Did you `uv sync --extra dev` and activate the venv?") from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
