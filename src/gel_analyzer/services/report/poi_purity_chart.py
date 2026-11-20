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
    mean: tuple[float, str] | None = None,
) -> BytesIO | None:
    """
    Render a POI purity bar chart with matplotlib.

    Args:
        data: List of dicts with keys 'label' (str) and 'purity' (float|None), optionally 'note' (str: why the
              lane has no purity, shown in its slot instead of a bar) and 'muted' (bool: a hatched bar, a lane
              the mean leaves out). Entries with purity=None and no note are skipped.
        figsize: Figure size in inches (width, height).
        dpi: Resolution.
        dark_theme: True for dark background (Word report), False for white (Excel/PPT).
        mean: (value, text) of the gel's mean purity, drawn as a line; None draws none.

    Returns:
        BytesIO with PNG image, or None if no purity data available.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    # Filter to entries that have purity data, or a note saying why they have none
    filtered = [d for d in data if d.get("purity") is not None or d.get("note")]
    if not any(d.get("purity") is not None for d in filtered):
        return None

    labels = [d["label"] for d in filtered]
    notes = [d.get("note") if d.get("purity") is None else None for d in filtered]
    purities = [d["purity"] if d.get("purity") is not None else 0.0 for d in filtered]
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
    for bar, entry in zip(bars, filtered, strict=False):
        if entry.get("muted"):
            bar.set_facecolor("none")
            bar.set_edgecolor(text_color)
            bar.set_hatch("///")

    # Value labels above bars; a lane with no purity says why, at the foot of its slot
    for bar, purity, note in zip(bars, purities, notes, strict=False):
        if note:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                2,
                note,
                ha="center",
                va="bottom",
                rotation=90,
                fontsize=8,
                fontstyle="italic",
                color="#8a8a8a",
                zorder=4,
            )
            continue
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

    if mean is not None:
        ax.axhline(y=mean[0], color=text_color, linestyle=":", linewidth=1.3, zorder=2, label=mean[1])

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
    handles, _labels = ax.get_legend_handles_labels()
    if any(entry.get("muted") for entry in filtered):
        from matplotlib.patches import Patch

        handles.append(
            Patch(facecolor="none", edgecolor=text_color, hatch="///", label="Control lane (not in the mean)")
        )
    # Above the plot, under the title: inside it, the legend sat on the tallest bars.
    legend = ax.legend(
        handles=handles,
        loc="lower left",
        bbox_to_anchor=(0.0, 1.0),
        ncol=len(handles),
        fontsize=8,
        frameon=False,
    )
    for text in legend.get_texts():
        text.set_color(text_color)

    ax.set_title(
        "POI Purity Across Samples",
        color=text_color,
        fontsize=11,
        fontweight="bold",
        loc="left",
        pad=24,
    )

    plt.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf
