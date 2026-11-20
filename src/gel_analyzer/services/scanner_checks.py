"""
What the scanner recorded about an image, checked against its declared gel type.

Bio-Rad ``.scn`` files record the scan mode (``scanner_metadata["application"]``,
read by ``services/scn_parser.py``). The production audit of 2026-10-02 (spec
``docs/superpowers/specs/2026-10-02-gel-assays-readouts-design.md`` §0 item 8)
found ``Colorimetric`` on 95 of the 96 western blots and ``Coomassie Blue`` on
SDS-PAGE gels -- a better witness of the gel type than the YOLO inference, which
said SDS-PAGE for 159 of 161 westerns.

The check only WARNS: a stained gel of a western's membrane can be scanned as
Coomassie Blue and be right. Nothing is blocked or rewritten.
"""

from gel_analyzer.models import GelImage

# Scan mode keyword (case-insensitive, contained in the recorded application) →
# the gel type it usually means. Source: the audit above.
SCANNER_APPLICATION_GEL_TYPE = {
    "coomassie": GelImage.GelType.SDS_PAGE,
    "colorimetric": GelImage.GelType.WESTERN_BLOT,
}

# How the warning names the usual gel type.
_USUALLY = {
    GelImage.GelType.SDS_PAGE: "an SDS-PAGE",
    GelImage.GelType.WESTERN_BLOT: "a western blot",
}


def scanner_type_mismatch(gel_image) -> str | None:
    """A warning when the scan mode contradicts the gel type, else ``None``.

    A Coomassie scan of a gel not typed SDS-PAGE, or a Colorimetric scan of a gel
    typed SDS-PAGE. A Colorimetric dot blot is not flagged: only the SDS-PAGE /
    not-SDS-PAGE split decides whether a purity is written.
    """
    metadata = gel_image.scanner_metadata if isinstance(gel_image.scanner_metadata, dict) else {}
    application = str(metadata.get("application") or "").strip()
    if not application:
        return None
    lowered = application.lower()
    is_sds_page = gel_image.gel_type == GelImage.GelType.SDS_PAGE
    for keyword, usual_type in SCANNER_APPLICATION_GEL_TYPE.items():
        if keyword not in lowered:
            continue
        usually_sds_page = usual_type == GelImage.GelType.SDS_PAGE
        if usually_sds_page != is_sds_page:
            usually = _USUALLY.get(usual_type, GelImage.GelType(usual_type).label)
            return f"The scanner recorded this image as {application}, which is usually {usually}. Check the gel type."
    return None
