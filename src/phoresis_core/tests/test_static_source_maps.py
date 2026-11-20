"""Every source map a shipped script or stylesheet names must ship with it.

The production static storage (WhiteNoise's CompressedManifestStaticFilesStorage) rewrites the
``sourceMappingURL`` of each file and stops ``collectstatic`` when the map is missing -- and
``collectstatic`` runs in the container's entrypoint, so the application does not start. Neither the
test settings nor ``runserver`` use that storage: without this test the first sign is a release that
does not boot (seen 2026-11-20 with a vendored ``ort.min.js``, caught on a local image build).
"""

import re
from pathlib import Path

from django.conf import settings

SOURCE_MAP = re.compile(rb"sourceMappingURL=([^\s*'\"]+)")


def test_every_named_source_map_is_shipped():
    missing = []
    for path in Path(settings.SRC_DIR).glob("*/static/**/*"):
        if path.suffix not in {".js", ".mjs", ".css"} or not path.is_file():
            continue
        # The comment sits at the end of the file; a minified bundle can be megabytes long.
        tail = path.read_bytes()[-512:]
        for name in SOURCE_MAP.findall(tail):
            target = name.decode("utf-8", errors="replace")
            if target.startswith("data:"):
                continue
            if not (path.parent / target).is_file():
                missing.append(f"{path.relative_to(settings.SRC_DIR).as_posix()} -> {target}")
    assert not missing, "source maps named but not shipped: " + ", ".join(missing)
