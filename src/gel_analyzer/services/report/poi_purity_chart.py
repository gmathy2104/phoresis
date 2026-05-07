"""
Shared matplotlib renderer for POI purity bar chart.

Generates a bar chart showing POI purity (%) per sample with
threshold lines at target (90%) and minimum (70%) levels.
Used by Word, Excel, and PowerPoint report builders.
"""

from io import BytesIO

from phoresis_core.logging_config import get_logger

from .constants import (
    CHART_DARK_BG,
    CHART_DARK_GRID,
    CHART_DARK_TEXT,
    CHART_LIGHT_BG,
    CHART_LIGHT_GRID,
    CHART_LIGHT_TEXT,
    POI_PURITY_MINIMUM,
    POI_PURITY_TARGET,
    POI_PURITY_TIER_HIGH,
    POI_PURITY_TIER_LOW,
    POI_PURITY_TIER_MID,
)

logger = get_logger(__name__)


def render_poi_purity_chart(
    data: list[dict],
    figsize: tuple = (7, 3.5),
    dpi: int = 150,
    dark_theme: bool = True,
) -> BytesIO | None:
    """
    Render a POI purity bar chart with matplotlib.

    Args:
        data: List of dicts with keys 'label' (str) and 'purity' (float|None).
              Entries with purity=None are skipped.
        figsize: Figure size in inches (width, height).
        dpi: Resolution.
        dark_theme: True for dark background (Word report), False for white (Excel/PPT).

    Returns:
        BytesIO with PNG image, or None if no purity data available.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    # Filter to entries that have purity data
    filtered = [d for d in data if d.get("purity") is not None]
    if not filtered:
        return None

    labels = [d["label"] for d in filtered]
    purities = [d["purity"] for d in filtered]
    n = len(labels)

    # Tier-based bar colours — matches the live densitometry POI-purity
    # bar chart (>=target → green, >=minimum → amber, below → red).
    def _tier_color(p: float) -> str:
        if p >= POI_PURITY_TARGET:
            return POI_PURITY_TIER_HIGH
        if p >= POI_PURITY_MINIMUM:
            return POI_PURITY_TIER_MID
        return POI_PURITY_TIER_LOW

    colors = [_tier_color(p) for p in purities]

    # Theme colors — same chart palette in both themes; only the canvas
    # chrome flips. Threshold lines stay green/amber to mirror the web.
    if dark_theme:
        bg_color = CHART_DARK_BG
        text_color = CHART_DARK_TEXT
        grid_color = CHART_DARK_GRID
    else:
        bg_color = CHART_LIGHT_BG
        text_color = CHART_LIGHT_TEXT
        grid_color = CHART_LIGHT_GRID
    target_color = POI_PURITY_TIER_HIGH
    minimum_color = POI_PURITY_TIER_MID

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)

    x = np.arange(n)
    bar_width = min(0.6, 0.8 / max(1, n / 6))
    bars = ax.bar(x, purities, width=bar_width, color=colors, zorder=3)

    # Value labels above bars
    for bar, purity in zip(bars, purities, strict=False):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.5,
            f"{purity:.1f}%",
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold",
            color=text_color,
            zorder=4,
        )

    # Threshold lines
    ax.axhline(
        y=POI_PURITY_TARGET,
        color=target_color,
        linestyle="--",
        linewidth=1.5,
        zorder=2,
        label=f"Target ({POI_PURITY_TARGET}%)",
    )
    ax.axhline(
        y=POI_PURITY_MINIMUM,
        color=minimum_color,
        linestyle="--",
        linewidth=1.5,
        zorder=2,
        label=f"Minimum ({POI_PURITY_MINIMUM}%)",
    )

    # Axis styling
    ax.set_xticks(x)
    ax.set_xticklabels(
        [label[:18] + "..." if len(label) > 18 else label for label in labels],
        rotation=30 if n > 4 else 0,
        ha="right" if n > 4 else "center",
        fontsize=8,
        color=text_color,
    )
    ax.set_ylabel("POI Purity (%)", color=text_color, fontsize=9)
    ax.set_ylim(0, max(max(purities) + 10, POI_PURITY_TARGET + 10))
    ax.tick_params(colors=text_color, labelsize=8)
    ax.yaxis.grid(True, color=grid_color, linewidth=0.5, zorder=1)
    ax.set_axisbelow(True)

    for spine in ax.spines.values():
        spine.set_color(grid_color)

    # Legend
    legend = ax.legend(
        loc="upper right",
        fontsize=8,
        framealpha=0.8,
        facecolor=bg_color,
        edgecolor=grid_color,
    )
    for text in legend.get_texts():
        text.set_color(text_color)

    ax.set_title(
        "POI Purity Across Samples",
        color=text_color,
        fontsize=11,
        fontweight="bold",
        pad=10,
    )

    plt.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf
