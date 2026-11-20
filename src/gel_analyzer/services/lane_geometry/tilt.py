"""Each detected lane's tilt, measured on the display image and smoothed by a whole-gel fan (spec 2026-10-10 §2).

One lane: the box widened by half its width on each side, cut into horizontal slices; each slice's column profile is
matched against the window's mean profile by zero-mean normalised correlation over the overlap (polarity-free); the
shifts, weighted (normalised per lane, capped), give the axis by a Huber line fit; a second pass de-tilts the slices
and rebuilds the reference. The gel: slope = a + b * x across the measured lanes (b = 0 for a rotated gel), weighted
by 1 / (sigma_i^2 + tau^2). The slope a lane gets follows ``slope_rule``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

SLICES = 12
MIN_SLICE_HEIGHT = 20
MIN_SLICES = 5
MIN_COVERAGE = 0.5
MIN_CORRELATION = 0.3
MIN_CONTRAST = 1.0
WEIGHT_CAP = 3.0
HUBER_C = 1.345
MAX_SLOPE = 0.15
MIN_DRIFT_PX = 2.0
MIN_SIGMA = 1e-4
MAX_SIGMA_PX = 5.0
MASK_CONTRADICTION_PX = 10.0

# What the app runs (spec §10, the owner's choice after the bench, §9): the guarded mask slope, lanes under 4 px of
# drift kept straight. The other rules and MIN_DRIFT_PX's default are the bench's.
APP_SLOPE_RULE = "mask_guarded"
APP_MIN_DRIFT_PX = 4.0
SLOPE_RULES = ("own", "model", "consistent", "own_or_model", "mask", "mask_guarded", "consistent_reliable")
WIDTH_RULES = ("box", "box_minus_drift")


@dataclass(frozen=True)
class LaneMeasure:
    index: int
    box: tuple
    slope: float | None
    x_mid: float | None
    sigma: float | None


@dataclass(frozen=True)
class GelModel:
    a: float
    b: float
    y_ref: float
    lanes_used: int
    tau: float

    def slope_at(self, x: float) -> float:
        return self.a + self.b * x


@dataclass(frozen=True)
class LaneTilt:
    index: int
    x_ref: float
    slope: float
    width: float
    slope_measured: float | None
    sigma: float | None
    source: str


@dataclass(frozen=True)
class TiltResult:
    lanes: list
    model: GelModel | None
    y_ref: float


def _best_lag(profile: np.ndarray, reference: np.ndarray, max_lag: int) -> tuple[float, float] | None:
    """Sub-pixel d such that profile(x) ~ reference(x - d), and the peak's sharpness; None when nothing matches."""
    n = len(profile)
    lags = np.arange(-max_lag, max_lag + 1)
    scores = np.full(len(lags), -1.0)
    for k, d in enumerate(lags):
        if d >= 0:
            a, b = profile[d:], reference[: n - d]
        else:
            a, b = profile[: n + d], reference[-d:]
        if len(a) < n // 2:
            continue
        a = a - a.mean()
        b = b - b.mean()
        den = math.sqrt(float((a * a).sum() * (b * b).sum()))
        if den > 0:
            scores[k] = float((a * b).sum() / den)
    k = int(np.argmax(scores))
    peak = scores[k]
    if peak < MIN_CORRELATION:
        return None
    offset = 0.0
    if 0 < k < len(lags) - 1 and scores[k - 1] > -1 and scores[k + 1] > -1:
        left, right = scores[k - 1], scores[k + 1]
        den = left - 2 * peak + right
        if den < 0:
            offset = 0.5 * (left - right) / den
    sharpness = max(0.0, peak - float(np.median(scores[scores > -1])))
    return float(lags[k] + offset), sharpness


def _huber_line(t: np.ndarray, v: np.ndarray, w: np.ndarray) -> tuple[float, float, float]:
    """v = c + s * t by weighted Huber IRLS; returns c, s and the slope's standard error."""
    design = np.vstack([np.ones_like(t), t]).T
    weights = w.copy()
    scale = 1e-6
    coef = np.zeros(2)
    for _ in range(25):
        root = np.sqrt(weights)
        coef, *_ = np.linalg.lstsq(design * root[:, None], v * root, rcond=None)
        resid = v - design @ coef
        scale = max(1.4826 * float(np.median(np.abs(resid - np.median(resid)))), 1e-6)
        u = np.abs(resid) / (HUBER_C * scale)
        updated = w * np.where(u <= 1, 1.0, 1.0 / np.maximum(u, 1e-12))
        if np.allclose(updated, weights, rtol=1e-6, atol=1e-12):
            weights = updated
            break
        weights = updated
    n_eff = float(w.sum() ** 2 / (w**2).sum())
    t_bar = float(np.average(t, weights=weights))
    spread = float(np.average((t - t_bar) ** 2, weights=weights)) * n_eff
    sigma = scale / math.sqrt(spread) if spread > 0 else math.inf
    return float(coef[0]), float(coef[1]), sigma


def measure_lane(gray: np.ndarray, box: tuple, index: int = 0) -> LaneMeasure:
    """The lane's own axis, or a LaneMeasure with slope None when the window holds too little signal.

    ``x_mid`` is the box centre moved by the fitted intercept: a shift relative to the window's mean profile, so the
    lane's position stays the model's and only its tilt is measured.
    """
    x, y, w, h = (float(v) for v in box)
    height, width = gray.shape[:2]
    x0, x1 = max(0, math.floor(x - w / 2)), min(width, math.ceil(x + w + w / 2))
    y0, y1 = max(0, math.floor(y)), min(height, math.ceil(y + h))
    none = LaneMeasure(index, tuple(box), None, None, None)
    window = gray[y0:y1, x0:x1].astype(np.float64)
    count = min(SLICES, window.shape[0] // MIN_SLICE_HEIGHT)
    if count < MIN_SLICES or window.shape[1] < 8:
        return none
    edges = np.linspace(0, window.shape[0], count + 1).round().astype(int)
    profiles = [window[edges[i] : edges[i + 1]].mean(axis=0) for i in range(count)]
    centres = np.array([(edges[i] + edges[i + 1]) / 2 for i in range(count)])
    y_mid_local = window.shape[0] / 2
    max_lag = max(1, int(w / 2))
    columns = np.arange(window.shape[1], dtype=np.float64)
    reference = window.mean(axis=0)
    fit = None
    for _ in range(2):
        shifts, weights, used_rows, used = [], [], 0, []
        for i, profile in enumerate(profiles):
            contrast = float(np.percentile(profile, 95) - np.percentile(profile, 5))
            if contrast < MIN_CONTRAST:
                continue
            match = _best_lag(profile, reference, max_lag)
            if match is None:
                continue
            shifts.append(match[0])
            weights.append(contrast * match[1])
            used_rows += edges[i + 1] - edges[i]
            used.append(i)
        if len(used) < MIN_SLICES or used_rows < MIN_COVERAGE * window.shape[0] or sum(weights) <= 0:
            return none
        weight = np.array(weights) / sum(weights)
        weight = np.minimum(weight, WEIGHT_CAP * float(np.median(weight)))
        weight = weight / weight.sum()
        t = centres[used] - y_mid_local
        fit = _huber_line(t, np.array(shifts), weight)
        intercept, slope, _sigma = fit
        aligned = [
            np.interp(columns + intercept + slope * (centres[i] - y_mid_local), columns, profiles[i]) for i in used
        ]
        reference = np.average(np.array(aligned), axis=0, weights=weight)
    intercept, slope, sigma = fit
    x_mid = x + w / 2 + intercept
    return LaneMeasure(index, tuple(box), slope, x_mid, max(sigma, MIN_SIGMA))


def _fit_fan(
    x: np.ndarray, s: np.ndarray, sigma: np.ndarray, linear: bool
) -> tuple[float, float, float, np.ndarray, float]:
    """s = a + b * x weighted by 1 / (sigma^2 + tau^2), tau iterated; returns a, b, tau, residuals, se(b)."""
    x_bar = float(x.mean())
    xc = x - x_bar
    tau = 0.0
    a_c = b = se_b = 0.0
    resid = s.copy()
    for _ in range(25):
        w = 1.0 / (sigma**2 + tau**2)
        if linear:
            design = np.vstack([np.ones_like(xc), xc]).T
            root = np.sqrt(w)
            coef, *_ = np.linalg.lstsq(design * root[:, None], s * root, rcond=None)
            a_c, b = float(coef[0]), float(coef[1])
            cov = np.linalg.pinv((design * w[:, None]).T @ design)
            se_b = math.sqrt(max(float(cov[1, 1]), 0.0))
        else:
            a_c, b, se_b = float(np.average(s, weights=w)), 0.0, 0.0
        resid = s - (a_c + b * xc)
        dof = max(1, len(s) - (2 if linear else 1))
        new_tau = math.sqrt(max(0.0, float((resid**2).sum()) / dof - float(np.mean(sigma**2))))
        converged = abs(new_tau - tau) < 1e-7
        tau = new_tau
        if converged:
            break
    return a_c - b * x_bar, b, tau, resid, se_b


def fit_gel_model(measures: list, y_ref: float) -> GelModel | None:
    """The fan across the measured lanes; None with fewer than 2 (spec §2, *The gel model*)."""
    usable = [m for m in measures if m.slope is not None]
    if len(usable) < 2:
        return None
    x = np.array([m.x_mid + m.slope * (y_ref - (m.box[1] + m.box[3] / 2)) for m in usable])
    s = np.array([m.slope for m in usable])
    sigma = np.array([max(m.sigma, MIN_SIGMA) for m in usable])
    linear = len(usable) >= 4
    a, b, tau, resid, se_b = _fit_fan(x, s, sigma, linear)
    used = len(usable)
    if len(usable) >= 7:
        scale = 1.4826 * float(np.median(np.abs(resid - np.median(resid))))
        if scale > 0:
            keep = np.abs(resid) <= 3 * scale
            if not keep.all():
                a, b, tau, resid, se_b = _fit_fan(x[keep], s[keep], sigma[keep], linear)
                used = int(keep.sum())
    elif linear and (se_b == 0 or abs(b) < 2 * se_b):
        a, b, tau, resid, se_b = _fit_fan(x, s, sigma, False)
    return GelModel(a=a, b=b, y_ref=y_ref, lanes_used=used, tau=tau)


def _reliable(measure: LaneMeasure, max_sigma_px: float) -> LaneMeasure:
    """The measure, or one without a slope when its uncertainty over the lane's height exceeds ``max_sigma_px``."""
    if measure.slope is None or measure.sigma * float(measure.box[3]) <= max_sigma_px:
        return measure
    return LaneMeasure(measure.index, measure.box, None, None, None)


def tilt_lanes(
    gray: np.ndarray,
    boxes: list,
    slope_rule: str = "consistent",
    width_rule: str = "box",
    min_drift_px: float = MIN_DRIFT_PX,
    mask_slopes: dict | None = None,
    max_sigma_px: float = MAX_SIGMA_PX,
) -> TiltResult:
    """Every lane's axis (x at the gel's y_ref and a slope) and width, by the browser's index (spec §2, *Output*).

    A lane whose drift over its height stays under ``min_drift_px`` is straight. The gel model is read at the box's
    centre x (the box's mid-height is close to y_ref on a gel). ``mask_slopes`` ({index: slope or None}) are the lane
    model's own mask axes, used by the ``mask`` and ``mask_guarded`` rules; ``consistent_reliable`` and
    ``mask_guarded`` keep an image slope only when sigma x h <= ``max_sigma_px`` (bench amendment 2).
    """
    if slope_rule not in SLOPE_RULES or width_rule not in WIDTH_RULES:
        raise ValueError(f"slope_rule {slope_rule!r} / width_rule {width_rule!r}")
    mask_slopes = mask_slopes or {}
    measures = []
    for index, box in boxes:
        measure = measure_lane(gray, box, index)
        if measure.slope is not None and abs(measure.slope) > MAX_SLOPE:
            measure = LaneMeasure(index, tuple(box), None, None, None)
        if slope_rule in ("consistent_reliable", "mask_guarded"):
            measure = _reliable(measure, max_sigma_px)
        measures.append(measure)
    y_ref = float(np.median([b[1] + b[3] / 2 for _, b in boxes])) if boxes else 0.0
    uses_model = slope_rule in ("model", "consistent", "own_or_model", "consistent_reliable")
    model = fit_gel_model(measures, y_ref) if uses_model else None
    lanes = []
    for m in measures:
        x, y, w, h = (float(v) for v in m.box)
        y_mid = y + h / 2
        own = m.slope
        modelled = model.slope_at(x + w / 2) if model else None
        mask = mask_slopes.get(m.index)
        if mask is not None and abs(mask) > MAX_SLOPE:
            mask = None  # a degenerate mask leaves the lane straight (spec §10, *Bounds*)
        if slope_rule == "mask":
            slope, source = (mask, "mask") if mask is not None else (0.0, "straight")
        elif slope_rule == "mask_guarded":
            contradicted = (
                mask is not None and own is not None and own * mask < 0 and abs(own - mask) * h > MASK_CONTRADICTION_PX
            )
            if mask is None or contradicted:
                slope, source = 0.0, "straight"
            else:
                slope, source = mask, "mask"
        elif slope_rule == "consistent_reliable":
            if own is not None and modelled is not None and abs(own - modelled) <= 2 * m.sigma:
                slope, source = own, "measured"
            elif modelled is not None:
                slope, source = modelled, "gel_model"
            else:
                slope, source = (own, "measured") if own is not None else (0.0, "straight")
        elif slope_rule == "own":
            slope, source = (own, "measured") if own is not None else (0.0, "straight")
        elif slope_rule == "model":
            if modelled is not None:
                slope, source = modelled, "gel_model"
            else:
                slope, source = (own, "measured") if own is not None else (0.0, "straight")
        elif slope_rule == "own_or_model":
            if own is not None:
                slope, source = own, "measured"
            else:
                slope, source = (modelled, "gel_model") if modelled is not None else (0.0, "straight")
        else:  # consistent
            if own is not None and modelled is not None and abs(own - modelled) <= 2 * max(m.sigma, model.tau):
                slope, source = own, "measured"
            elif modelled is not None:
                slope, source = modelled, "gel_model"
            else:
                slope, source = (own, "measured") if own is not None else (0.0, "straight")
        if abs(slope) * h < min_drift_px:
            slope, source = 0.0, "straight"
        centre = m.x_mid if source == "measured" else x + w / 2
        width = w if width_rule == "box" else max(w - abs(slope) * h, 0.5 * w)
        lanes.append(LaneTilt(m.index, centre + slope * (y_ref - y_mid), slope, width, own, m.sigma, source))
    return TiltResult(lanes=lanes, model=model, y_ref=y_ref)
