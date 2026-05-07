"""
3D Terrain chart renderer for densitometry reports.

Renders a matplotlib 3D surface plot representing lane intensity profiles
as an elongated mountain ridge with Gaussian cross-section, band-colored
regions, contour lines on the surface, and dramatic lighting.

Band colours mirror the live gel-viewer overlay (see
``BAND_PALETTE_HEX`` in ``constants.py`` and the corresponding
``.gv-band.*`` rules in ``gel_viewer_standalone.css``) so a POI band
on the gel image and the same band on the terrain plot have the
same hue. Lookups are done by enum code, with a defensive fallback
to the display string for older callers.
"""

from io import BytesIO

import numpy as np

from phoresis_core.logging_config import get_logger

from .constants import BAND_TYPE_DISPLAY, CHART_BAND_PALETTE_HEX, CHART_PROFILE_COLOR

logger = get_logger(__name__)

# Build a forgiving lookup that accepts either the enum code (preferred)
# or the display string ("Protein of Interest", "MW Reference", …).
_BAND_DISPLAY_TO_CODE = {v: k for k, v in BAND_TYPE_DISPLAY.items()}
_BAND_DISPLAY_TO_CODE["MW Ladder"] = "MW_REFERENCE"  # legacy display alias

BAND_COLORS = {**CHART_BAND_PALETTE_HEX}
BAND_COLORS.update({display: CHART_BAND_PALETTE_HEX[code] for display, code in _BAND_DISPLAY_TO_CODE.items()})

BASELINE_COLOR = CHART_PROFILE_COLOR  # matches Three.js DEFAULT vertex + ground plane


def _band_color(band_type) -> str:
    """Resolve a band-type token (enum code or display string) to a hex color."""
    if band_type is None:
        return CHART_BAND_PALETTE_HEX["OTHER"]
    return BAND_COLORS.get(band_type, CHART_BAND_PALETTE_HEX["OTHER"])


def render_terrain_chart(
    lane_data,
    figsize: tuple = (10, 5),
    dpi: int = 180,
    dark_theme: bool = True,
    azimuth: float = -55,
    elevation: float = 28,
) -> BytesIO | None:
    """
    Render a 3D terrain surface chart for a single lane's intensity profile.

    Creates an elongated mountain ridge (not a square) matching the lane's
    aspect ratio: long along the migration axis, narrow across the depth.

    The surface represents:
    - X axis: position along the lane (migration direction)
    - Z axis: narrow Gaussian cross-section (lane width effect)
    - Y axis (up): intensity values

    Band regions are colored by proximity to band centers using ±3σ Gaussian
    falloff, matching the Three.js frontend renderer.

    Args:
        lane_data: LaneReportData with profile_data and bands
        figsize: matplotlib figure size
        dpi: output resolution
        dark_theme: use dark background matching densitometry UI
        azimuth: camera azimuth angle
        elevation: camera elevation angle

    Returns:
        BytesIO with PNG image, or None on failure
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource, to_rgba
    from scipy.ndimage import gaussian_filter1d

    if not lane_data.profile_data:
        return None

    profile = lane_data.profile_data
    intensities = np.array(profile.get("intensities", []), dtype=float)
    y_positions = np.array(profile.get("y_positions", []), dtype=float)

    if len(intensities) < 10 or len(y_positions) < 10:
        return None

    try:
        # ── Downsample to ~400 points ────────────────────────────────
        n_points = len(intensities)
        target_points = min(400, n_points)
        if n_points > target_points:
            indices = np.linspace(0, n_points - 1, target_points, dtype=int)
            intensities = intensities[indices]
            y_positions = y_positions[indices]

        # Light smoothing for nicer peaks (σ=2 samples)
        intensities = gaussian_filter1d(intensities, sigma=2.0)

        n = len(intensities)

        # Normalize intensities to [0, 1] for consistent scaling
        i_max = np.max(intensities)
        if i_max > 0:
            intensities_norm = intensities / i_max
        else:
            return None

        # ── Build elongated ridge geometry ────────────────────────────
        # Key insight: the lane is long (n points along X) but narrow
        # in depth (Z). We use ratio ~5:1 to create a ribbon, not a cube.
        n_depth = 20  # depth segments (cross-section)
        depth_half_width = 1.0  # narrow Gaussian half-extent

        # X: position along lane (0 to n-1)
        x_range = np.linspace(0, n - 1, n)
        # Z: narrow cross-section
        z_range = np.linspace(-depth_half_width, depth_half_width, n_depth)

        X, Z = np.meshgrid(x_range, z_range)

        # Gaussian cross-section (tight, factor 3.0 matching Three.js)
        gaussian_envelope = np.exp(-3.0 * z_range**2)

        # Y (height) = intensity × Gaussian envelope
        Y = np.outer(gaussian_envelope, intensities_norm)

        # Scale: height amplification for visual drama
        height_scale = 8.0
        Y = Y * height_scale

        # ── Band coloring ─────────────────────────────────────────────
        # Use ±3σ proximity (matching Three.js _getVertexColor logic)
        band_info = []
        for band in lane_data.bands:
            if band.position_y is not None:
                # Use peak sigma if available, else default ~15px
                sigma = 15.0
                if band.fwhm is not None and band.fwhm > 0:
                    sigma = band.fwhm / 2.355  # FWHM → σ
                elif band.peak_sigma is not None and band.peak_sigma > 0:
                    sigma = band.peak_sigma
                band_info.append(
                    {
                        "pos": float(band.position_y),
                        "type": band.band_type,
                        "sigma": sigma,
                    }
                )

        # Build per-vertex RGBA color array
        facecolors = np.empty(X.shape + (4,))
        base_rgba = np.array(to_rgba(BASELINE_COLOR, alpha=0.85))
        facecolors[:] = base_rgba

        if band_info:
            for xi in range(n):
                pos = y_positions[xi] if xi < len(y_positions) else xi
                best_dist = float("inf")
                best_type = None

                for bi in band_info:
                    dist = abs(pos - bi["pos"])
                    threshold = bi["sigma"] * 3.0
                    if dist <= threshold and dist < best_dist:
                        best_dist = dist
                        best_type = bi["type"]

                if best_type:
                    color_hex = _band_color(best_type)
                    band_rgba = np.array(to_rgba(color_hex, alpha=0.9))

                    # Fade by distance from band center for smooth transitions
                    sigma_val = next(
                        (
                            bi["sigma"]
                            for bi in band_info
                            if bi["type"] == best_type and abs(pos - bi["pos"]) == best_dist
                        ),
                        15.0,
                    )
                    fade = np.exp(-0.5 * (best_dist / max(sigma_val, 1.0)) ** 2)
                    blended = fade * band_rgba + (1 - fade) * base_rgba
                    blended[3] = 0.9  # keep alpha consistent

                    facecolors[:, xi] = blended

        # ── Intensity-based brightness modulation ─────────────────────
        # Brighter where peaks are higher (subtle effect)
        for zi in range(n_depth):
            for xi in range(n):
                brightness = 0.5 + 0.5 * intensities_norm[xi]
                facecolors[zi, xi, :3] *= brightness
                # Clamp
                facecolors[zi, xi, :3] = np.clip(facecolors[zi, xi, :3], 0, 1)

        # ── Edge fade: reduce alpha at the Z edges for soft ridge ─────
        for zi in range(n_depth):
            edge_fade = gaussian_envelope[zi]
            # Fade alpha near the edges to soften the ridge boundary
            alpha_min = 0.15
            facecolors[zi, :, 3] = alpha_min + (0.9 - alpha_min) * edge_fade

        # ── Create figure ─────────────────────────────────────────────
        bg_color = "#0f172a" if dark_theme else "#f8fafc"
        text_color = "#94a3b8" if dark_theme else "#334155"
        grid_color = "#475569" if dark_theme else "#cbd5e1"
        pane_color = "#1e293b" if dark_theme else "#f1f5f9"
        contour_color = "#ffffff" if dark_theme else "#64748b"

        fig = plt.figure(figsize=figsize, dpi=dpi)
        fig.patch.set_facecolor(bg_color)

        ax = fig.add_subplot(111, projection="3d", computed_zorder=False)
        ax.set_facecolor(bg_color)

        # ── Light source (matching Three.js directional light) ────────
        ls = LightSource(azdeg=225, altdeg=45)

        # ── Plot the surface ──────────────────────────────────────────
        ax.plot_surface(
            X,
            Z,
            Y,
            facecolors=facecolors,
            rstride=1,
            cstride=1,
            shade=True,
            lightsource=ls,
            antialiased=True,
            zorder=5,
        )

        # ── Contour lines on the surface (projected onto base) ────────
        try:
            n_contours = 10
            y_max = np.max(Y)
            if y_max > 0:
                levels = np.linspace(y_max * 0.05, y_max * 0.85, n_contours)
                ax.contour(
                    X,
                    Z,
                    Y,
                    levels=levels,
                    zdir="z",
                    offset=0,
                    colors=contour_color,
                    alpha=0.12,
                    linewidths=0.4,
                )
        except Exception:
            pass

        # ── Ridge silhouette line along the top ───────────────────────
        # Draw the intensity profile line on top of the ridge (z=0 center)
        ridge_y = intensities_norm * height_scale
        ridge_x = np.arange(n, dtype=float)
        ridge_z = np.zeros(n)
        ax.plot(
            ridge_x,
            ridge_z,
            ridge_y,
            color="white" if dark_theme else "#1e293b",
            linewidth=0.8,
            alpha=0.5,
            zorder=10,
        )

        # ── Semi-transparent ground plane ─────────────────────────────
        ground_color = "#2196F3" if dark_theme else "#93c5fd"
        gx = np.array([[0, n - 1], [0, n - 1]], dtype=float)
        gz = np.array([[-depth_half_width, -depth_half_width], [depth_half_width, depth_half_width]])
        gy = np.zeros_like(gx)
        ground_rgba = to_rgba(ground_color, alpha=0.04)
        ground_fc = np.full(gx.shape + (4,), ground_rgba)
        ax.plot_surface(
            gx,
            gz,
            gy,
            facecolors=ground_fc,
            shade=False,
            zorder=1,
        )

        # ── Peak markers (vertical lines at band positions) ──────────
        for bi in band_info:
            pos = bi["pos"]
            # Find closest x index
            idx = np.argmin(np.abs(y_positions - pos))
            if idx < n:
                peak_h = intensities_norm[idx] * height_scale
                color_hex = BAND_COLORS.get(bi["type"], BASELINE_COLOR)

                # Vertical dashed line from base to peak
                ax.plot(
                    [idx, idx],
                    [0, 0],
                    [0, peak_h],
                    color=color_hex,
                    linewidth=1.0,
                    linestyle="--",
                    alpha=0.5,
                    zorder=8,
                )

                # Peak dot
                ax.scatter(
                    [idx],
                    [0],
                    [peak_h + 0.15],
                    color=color_hex,
                    s=25,
                    edgecolors="white",
                    linewidths=0.8,
                    zorder=12,
                    depthshade=False,
                )

        # ── Camera & styling ──────────────────────────────────────────
        ax.view_init(elev=elevation, azim=azimuth)

        # Set aspect ratio to emphasize elongation:
        # X = long (position along lane), Y = narrow (depth cross-section),
        # Z = moderate (intensity height)
        ax.set_box_aspect([1.0, 0.15, 0.35])

        # Pane styling
        ax.xaxis.pane.fill = True
        ax.yaxis.pane.fill = True
        ax.zaxis.pane.fill = True
        pane_rgba = to_rgba(pane_color, alpha=0.3)
        ax.xaxis.pane.set_facecolor(pane_rgba)
        ax.yaxis.pane.set_facecolor(pane_rgba)
        ax.zaxis.pane.set_facecolor(pane_rgba)
        ax.xaxis.pane.set_edgecolor(grid_color)
        ax.yaxis.pane.set_edgecolor(grid_color)
        ax.zaxis.pane.set_edgecolor(grid_color)

        # Grid styling
        ax.xaxis._axinfo["grid"]["color"] = grid_color
        ax.yaxis._axinfo["grid"]["color"] = grid_color
        ax.zaxis._axinfo["grid"]["color"] = grid_color
        ax.xaxis._axinfo["grid"]["linewidth"] = 0.3
        ax.yaxis._axinfo["grid"]["linewidth"] = 0.3
        ax.zaxis._axinfo["grid"]["linewidth"] = 0.3

        # Tick styling
        ax.tick_params(axis="x", colors=text_color, labelsize=6, pad=-2)
        ax.tick_params(axis="z", colors=text_color, labelsize=6, pad=-1)
        # Hide depth (Y) ticks — not meaningful to the user
        ax.set_yticks([])
        ax.set_ylabel("")

        # Axis labels
        ax.set_xlabel("Position", color=text_color, fontsize=7.5, labelpad=2, fontstyle="italic")
        ax.set_zlabel("Intensity", color=text_color, fontsize=7.5, labelpad=2, fontstyle="italic")

        # Simplify x-axis ticks (show ~5 ticks)
        n_xticks = min(5, n // 10)
        if n_xticks > 1:
            tick_indices = np.linspace(0, n - 1, n_xticks, dtype=int)
            ax.set_xticks(tick_indices)
            ax.set_xticklabels([f"{int(y_positions[i])}" for i in tick_indices], fontsize=6)

        # Simplify z-axis ticks (intensity)
        z_max = height_scale
        z_ticks = np.linspace(0, z_max * 0.8, 4)
        ax.set_zticks(z_ticks)
        # Show as % of max intensity
        ax.set_zticklabels([f"{v / height_scale * 100:.0f}%" for v in z_ticks], fontsize=6)

        # ── Title ─────────────────────────────────────────────────────
        sample_name = lane_data.sample_name or f"Lane {lane_data.lane_number}"
        ax.set_title(
            f"{sample_name} — 3D Intensity Profile",
            color=text_color,
            fontsize=10,
            fontweight="bold",
            pad=8,
            loc="left",
        )

        # ── Band legend ──────────────────────────────────────────────
        # Only show legend if there are colored bands
        if band_info:
            seen_types = set()
            legend_handles = []
            import matplotlib.patches as mpatches

            for bi in band_info:
                bt = bi["type"]
                if bt not in seen_types:
                    seen_types.add(bt)
                    color_hex = BAND_COLORS.get(bt, BASELINE_COLOR)
                    patch = mpatches.Patch(
                        facecolor=color_hex,
                        edgecolor="white",
                        linewidth=0.5,
                        label=bt,
                    )
                    legend_handles.append(patch)

            if legend_handles:
                leg = ax.legend(
                    handles=legend_handles,
                    loc="upper right",
                    fontsize=6.5,
                    framealpha=0.6,
                    facecolor=bg_color,
                    edgecolor=grid_color,
                    labelcolor=text_color,
                    borderpad=0.4,
                    handlelength=1.2,
                    handleheight=0.7,
                )
                leg.set_zorder(20)

        plt.subplots_adjust(left=0.02, right=0.95, top=0.92, bottom=0.05)

        buf = BytesIO()
        fig.savefig(
            buf,
            format="png",
            facecolor=fig.get_facecolor(),
            bbox_inches="tight",
            pad_inches=0.15,
        )
        plt.close(fig)
        buf.seek(0)
        return buf

    except Exception as e:
        logger.warning(f"Failed to render terrain chart: {e}", exc_info=True)
        return None
