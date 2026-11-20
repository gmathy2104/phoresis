"""The gel inside a scanned page.

Some gels -- most of them western blots -- are scanned as a page: the blot is
about a third of the image, on white (or black) paper. Given whole to the band
model at its input size, the blot's bands arrive ~3x smaller than any it
learned. The page is told by the image's frame: uniform and near-saturated.

Ported verbatim from ds-hub-django (``ml_annotator/services/cv2_detect.py``),
where the model's training set is cropped by the same rule: the browser must
show the model the gel at the scale it was trained on. Changing a constant here
changes what the model sees.
"""

import numpy as np

PAGE_LEVELS = (10.0, 245.0)  # a frame median at or beyond these is paper, not a gel's background
PAGE_TOLERANCE = 25  # grey levels from the paper's median still counted as paper
GEL_MIN_FILL = 0.6  # a blot is SOLID off-paper; a pale gel's bands on white are scattered


def gel_window(grey: np.ndarray) -> tuple[int, int, int, int] | None:
    """(x, y, w, h) of the gel inside a scanned page, padded 2 %, or None when the image is no page scan: a frame
    that is not near-white or near-black, a blot under 3 % or over 90 % of the image, or one not solid enough to be
    a gel."""
    import cv2  # noqa: PLC0415

    h, w = grey.shape[:2]
    b = max(2, int(0.02 * min(h, w)))
    frame = np.concatenate([grey[:b].ravel(), grey[-b:].ravel(), grey[:, :b].ravel(), grey[:, -b:].ravel()])
    page = float(np.median(frame))
    if PAGE_LEVELS[0] < page < PAGE_LEVELS[1]:
        return None
    off = (np.abs(grey.astype(np.int16) - page) > PAGE_TOLERANCE).astype(np.uint8)
    closed = cv2.morphologyEx(off, cv2.MORPH_CLOSE, np.ones((31, 31), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(closed)
    if n <= 1:
        return None
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, ww, hh = (int(v) for v in stats[k, :4])
    if not 0.03 <= ww * hh / (w * h) <= 0.9 or off[y : y + hh, x : x + ww].mean() < GEL_MIN_FILL:
        return None
    pad = int(round(0.02 * max(ww, hh)))
    x0, y0 = max(0, x - pad), max(0, y - pad)
    return x0, y0, min(w, x + ww + pad) - x0, min(h, y + hh + pad) - y0
