"""
The chart of a gel's readout, for the reports: the analysis page's lane values, one bar per lane.

- ``PURITY``: the POI purity bars (``poi_purity_chart``), the mean purity as a line, a control hatched;
- ``MOLECULE_VARIANTS``: one stacked bar per lane, HMWS / main band / LMWS;
- ``HOST_CELL_PROTEINS``: the HCP signal in % of the reference lane, the reference outlined; on a blot with no
  reference lane, the raw signal (arbitrary units, this blot only), as the page falls back to it;
- ``NONE``: no chart -- nothing is measured on that gel.

Every number is the lane's ``readout_numbers`` (``page_rows``: the page's own values); a lane with no value shows
the page's reason in its slot, never a zero bar. Until 2026-10-13 every gel got the purity chart of the raw POI
share, with its 90 % / 70 % lines: 0.0 % on each lane of an anti-HCP blot.
"""

from __future__ import annotations

from io import BytesIO

from gel_analyzer.models import GelAssay, Lane
from gel_analyzer.services.readouts import HCP_VALUE_KEYS, VARIANT_VALUE_KEYS

Readout = GelAssay.Readout
HCP_PERCENT, HCP_TOTAL, _HCP_BANDS = HCP_VALUE_KEYS

# The chart's slide / section title, by readout.
CHART_TITLES = {
    Readout.PURITY: "POI Purity",
    Readout.MOLECULE_VARIANTS: "HMWS / main band / LMWS",
    Readout.HOST_CELL_PROTEINS: "HCP % of reference",
}

# HMWS / main band / LMWS: the page's swatches for the three roles (amber, purple, sky).
_VARIANT_COLORS = ("#F59E0B", "#A855F7", "#38BDF8")
_VARIANT_LABELS = ("HMWS", "Main band", "LMWS")
_HCP_COLOR = "#0E7490"
_NOTE_COLOR = "#8a8a8a"


# An anti-HCP blot with no lane in % of a reference (no reference lane): its chart shows the raw signal.
NO_REFERENCE_TITLE = "HCP signal (no reference lane)"


def chart_title(readout: str, lanes=()) -> str | None:
    """The title of the readout's chart for these lanes; None when the readout has no chart."""
    if readout == Readout.HOST_CELL_PROTEINS and not _by_reference(lanes):
        return NO_REFERENCE_TITLE
    return CHART_TITLES.get(readout)


def _by_reference(lanes) -> bool:
    """Whether a lane of the blot has its HCP signal in % of the reference lane."""
    return any(lane.readout_numbers.get(HCP_PERCENT) is not None for lane in lanes if HCP_PERCENT in lane.readout_cells)


def lane_label(lane) -> str:
    """``L<n> <sample>`` -- the lane number first: two lanes can hold the same sample."""
    sample = lane.sample or ""
    return f"L{lane.lane_number} {sample}".strip()


def _reason(lane, key):
    cell = lane.readout_cells.get(key) or {}
    return cell.get("reason") or "—"


def render_readout_chart(
    readout: str,
    lanes,
    *,
    mean: tuple[float, str] | None = None,
    figsize: tuple = (10, 4.5),
    dpi: int = 150,
    dark_theme: bool = False,
) -> BytesIO | None:
    """The readout's chart (module docstring) as a PNG, or None when there is nothing to draw.

    ``lanes``: the report's lanes with their page values (``page_rows.apply_page_rows``). ``mean``: the gel's
    mean purity (value, text), drawn on a purity chart only.
    """
    if readout == Readout.PURITY:
        from .poi_purity_chart import render_poi_purity_chart

        entries = [
            {
                "label": lane_label(lane),
                "purity": lane.readout_numbers.get("purity"),
                "note": _reason(lane, "purity") if lane.readout_numbers.get("purity") is None else None,
                "muted": lane.lane_type_code == Lane.LaneType.CONTROL,
            }
            for lane in lanes
            if "purity" in lane.readout_cells
        ]
        return render_poi_purity_chart(entries, figsize=figsize, dpi=dpi, dark_theme=dark_theme, mean=mean)
    if readout == Readout.MOLECULE_VARIANTS:
        return _variants_chart(lanes, figsize, dpi, dark_theme)
    if readout == Readout.HOST_CELL_PROTEINS:
        return _hcp_chart(lanes, figsize, dpi, dark_theme)
    return None


def _figure(figsize, dpi, dark_theme):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    theme = {
        "bg": "#1e1e22" if dark_theme else "#ffffff",
        "text": "#e0e0e0" if dark_theme else "#333333",
        "grid": "#404040" if dark_theme else "#e0e0e0",
    }
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    fig.patch.set_facecolor(theme["bg"])
    ax.set_facecolor(theme["bg"])
    return plt, fig, ax, theme


def _finish(plt, fig, ax, theme, labels, title, ylabel, legend_order=None):
    """Axes, legend (above the plot, under the title: inside, it sat on the tallest bars), title; the PNG.

    ``legend_order``: the legend's labels in the order to show them; None keeps the drawing order.
    """
    import numpy as np

    n = len(labels)
    ax.set_xticks(np.arange(n))
    ax.set_xticklabels(
        [label[:20] + "…" if len(label) > 20 else label for label in labels],
        rotation=30 if n > 4 else 0,
        ha="right" if n > 4 else "center",
        fontsize=8,
        color=theme["text"],
    )
    ax.set_ylabel(ylabel, color=theme["text"], fontsize=9)
    ax.tick_params(colors=theme["text"], labelsize=8)
    ax.yaxis.grid(True, color=theme["grid"], linewidth=0.5, zorder=1)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_color(theme["grid"])
    handles, names = ax.get_legend_handles_labels()
    if legend_order is not None:
        handles = [handles[names.index(name)] for name in legend_order if name in names]
    if handles:
        legend = ax.legend(
            handles=handles, loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=len(handles), fontsize=8, frameon=False
        )
        for text in legend.get_texts():
            text.set_color(theme["text"])
    ax.set_title(title, color=theme["text"], fontsize=11, fontweight="bold", loc="left", pad=24 if handles else 10)
    plt.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def _note(ax, x, text):
    ax.text(x, 2, text, ha="center", va="bottom", rotation=90, fontsize=8, fontstyle="italic", color=_NOTE_COLOR)


def _variants_chart(lanes, figsize, dpi, dark_theme):
    """One stacked bar per lane the page reads: HMWS at the top, the main band, LMWS at the foot."""
    aggregates, main, fragments = VARIANT_VALUE_KEYS
    read = [lane for lane in lanes if main in lane.readout_cells]
    if not any(lane.readout_numbers.get(main) is not None for lane in read):
        return None
    plt, fig, ax, theme = _figure(figsize, dpi, dark_theme)
    width = min(0.6, 0.8 / max(1, len(read) / 6))
    for i, lane in enumerate(read):
        values = [lane.readout_numbers.get(key) for key in (fragments, main, aggregates)]
        if values[1] is None:
            _note(ax, i, _reason(lane, main))
            continue
        bottom = 0.0
        for value, color, label in zip(values, _VARIANT_COLORS[::-1], _VARIANT_LABELS[::-1], strict=False):
            ax.bar(i, value, width=width, bottom=bottom, color=color, zorder=3, label=label if i == 0 else None)
            bottom += value
        ax.text(
            i,
            values[0] + values[1] / 2,
            f"{values[1]:.1f}",
            ha="center",
            va="center",
            fontsize=8,
            fontweight="bold",
            color="#ffffff",
            zorder=4,
        )
    ax.set_ylim(0, 105)
    # The legend in reading order: the top of the stack first.
    return _finish(
        plt,
        fig,
        ax,
        theme,
        [lane_label(lane) for lane in read],
        CHART_TITLES[Readout.MOLECULE_VARIANTS],
        "% of lane",
        legend_order=_VARIANT_LABELS,
    )


def _hcp_chart(lanes, figsize, dpi, dark_theme):
    """The HCP signal per lane, in % of the reference lane; the raw signal when no lane has a % (no reference)."""
    read = [lane for lane in lanes if HCP_PERCENT in lane.readout_cells]
    by_reference = _by_reference(read)
    key = HCP_PERCENT if by_reference else HCP_TOTAL
    if not any(lane.readout_numbers.get(key) is not None for lane in read):
        return None
    plt, fig, ax, theme = _figure(figsize, dpi, dark_theme)
    width = min(0.6, 0.8 / max(1, len(read) / 6))
    for i, lane in enumerate(read):
        value = lane.readout_numbers.get(key)
        if value is None:
            _note(ax, i, _reason(lane, key))
            continue
        if lane.is_reference:
            ax.bar(i, value, width=width, color="none", edgecolor=_HCP_COLOR, linewidth=1.6, linestyle="--", zorder=3)
            text = "REF"
        else:
            ax.bar(i, value, width=width, color=_HCP_COLOR, zorder=3)
            text = f"{value:.1f}" if by_reference else f"{value:,.0f}"
        ax.text(i, value, text, ha="center", va="bottom", fontsize=8, fontweight="bold", color=theme["text"], zorder=4)
    if by_reference:
        ax.axhline(y=100, color=_HCP_COLOR, linestyle="--", linewidth=1.0, zorder=2, label="Reference lane = 100 %")
        title, ylabel = CHART_TITLES[Readout.HOST_CELL_PROTEINS], "% of the reference lane"
    else:
        title, ylabel = NO_REFERENCE_TITLE, "HCP signal (a.u., this blot only)"
    ax.set_ylim(0, ax.get_ylim()[1] * 1.08)
    return _finish(plt, fig, ax, theme, [lane_label(lane) for lane in read], title, ylabel)
