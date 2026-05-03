"""
Bio-Rad .scn file parser.

SCN files are MIME multipart containers produced by Bio-Rad ChemiDoc MP imagers
via Image Lab Touch software. The structure is nested:

    Top-level MIME
    ├── ItemHeaderTag (XML) — scan name, user, display settings
    ├── ScanImageTag0 (nested multipart/mixed)
    │   ├── ImageData (binary) — raw 16-bit pixels
    │   └── ImageHeader (XML) — dimensions, endianness, scanner attributes
    └── ItemProtocolSettingsTag (XML) — acquisition protocol

The ImageData and ImageHeader live inside the nested ScanImageTag0 part,
not at the top level. The scan_attributes in ImageHeader use XML element
attributes (name="..." value="..."), not text content.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


class SCNParseError(Exception):
    """Raised when an SCN file cannot be parsed."""

    pass


class SCNParser:
    """
    Parser for Bio-Rad .scn (MIME multipart) gel image files.

    Usage::

        if SCNParser.is_scn_file(path):
            img_array, metadata = SCNParser.parse(path)
    """

    SCN_MAGIC = b"MIME-Version:"

    @classmethod
    def is_scn_file(cls, file_path: Path) -> bool:
        """Check if a file is a Bio-Rad .scn file by inspecting the first bytes."""
        try:
            with open(file_path, "rb") as f:
                header = f.read(32)
            return header.startswith(cls.SCN_MAGIC)
        except OSError:
            return False

    @classmethod
    def parse(cls, file_path: Path) -> tuple[np.ndarray, dict]:
        """
        Parse an SCN file and extract the image array and metadata.

        Returns:
            Tuple of (numpy array with shape (H, W) dtype uint16, metadata dict).

        Raises:
            SCNParseError: If parsing fails.
        """
        log = logger.bind(file=str(file_path))
        log.info("Parsing SCN file")

        try:
            raw = file_path.read_bytes()
        except OSError as e:
            raise SCNParseError(f"Cannot read file: {e}") from e

        if not raw.startswith(cls.SCN_MAGIC):
            raise SCNParseError("Not a valid SCN file (missing MIME-Version header)")

        # Extract the top-level boundary
        boundary = cls._extract_boundary(raw)
        if not boundary:
            raise SCNParseError("Cannot find MIME boundary marker")

        # Split into top-level MIME parts
        parts = cls._split_parts(raw, boundary)
        if not parts:
            raise SCNParseError("No MIME parts found")

        log.debug(f"Found {len(parts)} top-level MIME parts")

        # Classify top-level parts and recurse into nested multipart
        image_data = None
        image_header_xml = None
        item_header_xml = None
        protocol_xml = None

        for headers, body in parts:
            desc = cls._get_header(headers, b"Content-Description")
            ctype = cls._get_header(headers, b"Content-Type")
            if desc is None:
                continue

            desc_lower = desc.lower()

            # Direct ImageData/ImageHeader at top level (simple structure)
            if b"imagedata" in desc_lower:
                image_data = body
            elif b"imageheader" in desc_lower:
                image_header_xml = body
            elif b"itemheadertag" in desc_lower:
                item_header_xml = body
            elif b"itemprotocolsettingstag" in desc_lower:
                protocol_xml = body
            elif b"scanimagetag" in desc_lower:
                # Nested multipart — contains ImageData + ImageHeader
                nested_boundary = cls._extract_boundary_from_content_type(ctype)
                if nested_boundary:
                    nested_parts = cls._split_parts(body, nested_boundary, skip_preamble=False)
                    log.debug(f"Found {len(nested_parts)} nested parts in ScanImageTag")
                    for nh, nb in nested_parts:
                        nd = cls._get_header(nh, b"Content-Description")
                        if nd is None:
                            continue
                        nd_lower = nd.lower()
                        if b"imagedata" in nd_lower and image_data is None:
                            image_data = nb
                        elif b"imageheader" in nd_lower and image_header_xml is None:
                            image_header_xml = nb

        if image_data is None:
            raise SCNParseError("No ImageData part found in SCN file")
        if image_header_xml is None:
            raise SCNParseError("No ImageHeader part found in SCN file")

        # Parse image dimensions and attributes from ImageHeader XML
        width, height, endian, scan_attrs = cls._parse_image_header(image_header_xml)

        # Determine byte order for numpy dtype
        dtype = "<u2" if endian == "little" else ">u2"

        expected_bytes = width * height * 2
        if len(image_data) < expected_bytes:
            raise SCNParseError(
                f"ImageData too short: expected {expected_bytes} bytes "
                f"for {width}x{height} image, got {len(image_data)}"
            )

        # Reconstruct the image array
        img_array = np.frombuffer(image_data[:expected_bytes], dtype=dtype).reshape((height, width))

        # NOTE: Raw pixels are returned as-is regardless of zero_is polarity.
        # For zero_is="white": 0=white bg, HIGH=dark bands → bands are peaks ✓
        # For zero_is="black": 0=dark bg, HIGH=bright bands → bands are peaks ✓
        # Callers needing display inversion should check metadata['zero_is'].

        # Build metadata dict
        metadata = cls._build_metadata(
            scan_attrs, item_header_xml, protocol_xml, width=width, height=height, endian=endian
        )

        log.info(f"Parsed SCN: {width}x{height}, 16-bit, scanner={metadata.get('scanner_model', 'unknown')}")

        return img_array, metadata

    # ── MIME helpers ──────────────────────────────────────────────

    @classmethod
    def _extract_boundary(cls, raw: bytes) -> bytes | None:
        """Extract the MIME boundary from the preamble Content-Type header."""
        header_end = raw.find(b"\r\n\r\n")
        if header_end == -1:
            header_end = raw.find(b"\n\n")
        if header_end == -1:
            header_end = min(2048, len(raw))

        header_section = raw[:header_end]
        return cls._extract_boundary_from_content_type(header_section)

    @classmethod
    def _extract_boundary_from_content_type(cls, header_bytes: bytes | None) -> bytes | None:
        """Extract boundary= value from a Content-Type header or header block."""
        if not header_bytes:
            return None
        match = re.search(rb'boundary="([^"]+)"', header_bytes, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        # Unquoted boundary
        match = re.search(rb"boundary=([^\r\n;\s]+)", header_bytes, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    @classmethod
    def _split_parts(cls, raw: bytes, boundary: bytes, skip_preamble: bool = True) -> list:
        """
        Split MIME body into parts using the boundary.

        Returns list of (headers_bytes, body_bytes) tuples.
        """
        delimiter = b"--" + boundary
        segments = raw.split(delimiter)

        parts = []
        start = 1 if skip_preamble else 0
        for segment in segments[start:]:
            # Check for closing boundary
            if segment.startswith(b"--"):
                break

            # Strip leading CRLF
            if segment.startswith(b"\r\n"):
                segment = segment[2:]
            elif segment.startswith(b"\n"):
                segment = segment[1:]

            # Split headers from body at the blank line
            for sep in (b"\r\n\r\n", b"\n\n"):
                idx = segment.find(sep)
                if idx != -1:
                    headers = segment[:idx]
                    body = segment[idx + len(sep) :]
                    # Strip trailing CRLF (before next boundary)
                    body = body.rstrip(b"\r\n")
                    parts.append((headers, body))
                    break

        return parts

    @classmethod
    def _get_header(cls, headers: bytes, name: bytes) -> bytes | None:
        """Get a header value by name (case-insensitive)."""
        name_lower = name.lower()
        for line in headers.split(b"\n"):
            line = line.strip(b"\r")
            if b":" in line:
                hdr_name, _, hdr_value = line.partition(b":")
                if hdr_name.strip().lower() == name_lower:
                    return hdr_value.strip()
        return None

    # ── XML parsing ──────────────────────────────────────────────

    @classmethod
    def _decode_xml(cls, xml_bytes: bytes) -> str:
        """Decode XML bytes, stripping any DOCTYPE declaration that ET can't handle."""
        try:
            text = xml_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = xml_bytes.decode("latin-1")
        # Strip <!DOCTYPE ...> which ET doesn't support
        text = re.sub(r"<!DOCTYPE[^>]*>", "", text)
        return text

    @classmethod
    def _parse_image_header(cls, xml_bytes: bytes) -> tuple[int, int, str, dict]:
        """
        Parse the ImageHeader XML to extract dimensions, endianness, and scan attributes.

        Real Bio-Rad format example::

            <root>
              <endian>little</endian>
              <size_pix width="2750" height="2200"/>
              <scan_attributes>
                <imager type="0" name="Imager" value="ChemiDoc MP"/>
                <exposure_time type="1" name="Exposure Time (sec)" value="0.428"/>
                <application type="0" name="Application" value="Coomassie Blue"/>
                <emission_filter type="0" name="Emission Filter" value="590/110 Filter"/>
                ...
              </scan_attributes>
            </root>

        Returns:
            (width, height, endian_str, scan_attributes_dict)
            scan_attributes_dict may include 'zero_is' key ('white' or 'black')
        """
        try:
            xml_str = cls._decode_xml(xml_bytes)
            root = ET.fromstring(xml_str)
        except ET.ParseError as e:
            raise SCNParseError(f"Invalid ImageHeader XML: {e}") from e

        # Extract dimensions from <size_pix width="W" height="H"/>
        width = None
        height = None
        size_el = root.find(".//size_pix")
        if size_el is not None:
            width = int(size_el.get("width", 0))
            height = int(size_el.get("height", 0))

        if not width or not height:
            raise SCNParseError("Cannot find image dimensions in ImageHeader XML")

        # Extract endianness
        endian = "little"
        endian_el = root.find(".//endian")
        if endian_el is not None and endian_el.text:
            endian = endian_el.text.strip().lower()

        # Extract image polarity: <image zero_is="white"/> means
        # low pixel values = white (background), high = dark (bands)
        image_el = root.find(".//image")
        zero_is = None
        if image_el is not None:
            zero_is = (image_el.get("zero_is") or "").strip().lower()

        # Extract scan attributes — Bio-Rad uses name/value XML attributes
        scan_attrs = {}
        scan_attr_el = root.find(".//scan_attributes")
        if scan_attr_el is not None:
            for child in scan_attr_el:
                # Real format: <tag name="Human Name" value="Value"/>
                name_attr = child.get("name", "")
                value_attr = child.get("value", "")
                tag = child.tag.lower()

                if value_attr:
                    # Map known fields to standard keys
                    name_lower = name_attr.lower()
                    if "imager" in name_lower or tag == "imager":
                        scan_attrs["scanner_model"] = value_attr
                    elif "exposure" in name_lower or tag == "exposure_time":
                        scan_attrs["exposure_time"] = value_attr
                    elif "application" in name_lower or tag == "application":
                        scan_attrs["application"] = value_attr
                    elif "emission" in name_lower or "filter" in name_lower:
                        scan_attrs["filter"] = value_attr
                    elif "excitation" in name_lower:
                        scan_attrs["excitation_source"] = value_attr
                    elif "serial" in name_lower:
                        scan_attrs["serial_number"] = value_attr
                    elif "flat" in name_lower:
                        scan_attrs["flat_field"] = value_attr
                    elif "software" in name_lower:
                        scan_attrs["software_version"] = value_attr
                    elif "image date" in name_lower:
                        scan_attrs["image_date"] = value_attr

                # Fallback: try text content (synthetic/older format)
                elif child.text and child.text.strip():
                    scan_attrs[tag] = child.text.strip()

        # Physical dimensions
        size_mm_el = root.find(".//size_mm")
        if size_mm_el is not None:
            w_mm = size_mm_el.get("width")
            h_mm = size_mm_el.get("height")
            if w_mm and h_mm:
                scan_attrs["physical_size_mm"] = f"{w_mm} x {h_mm} mm"

        # Store polarity for caller to handle inversion
        if zero_is:
            scan_attrs["zero_is"] = zero_is

        return width, height, endian, scan_attrs

    @classmethod
    def _build_metadata(
        cls,
        scan_attrs: dict,
        item_header_xml: bytes | None,
        protocol_xml: bytes | None,
        width: int,
        height: int,
        endian: str,
    ) -> dict:
        """Build a structured metadata dict from all XML parts."""
        metadata = {
            "source": "Bio-Rad SCN",
            "width": width,
            "height": height,
            "bit_depth": 16,
            "endianness": endian,
        }

        # Copy scan attributes
        metadata.update(scan_attrs)

        # Parse ItemHeaderTag for scan name / user info
        if item_header_xml:
            try:
                xml_str = cls._decode_xml(item_header_xml)
                root = ET.fromstring(xml_str)

                name_el = root.find(".//name")
                if name_el is not None and name_el.text and name_el.text.strip():
                    metadata["scan_name"] = name_el.text.strip()

                user_el = root.find(".//user")
                if user_el is not None and user_el.text and user_el.text.strip():
                    metadata["user"] = user_el.text.strip()

            except ET.ParseError:
                pass  # Non-critical

        # Parse protocol settings for acquisition info
        if protocol_xml:
            try:
                xml_str = cls._decode_xml(protocol_xml)
                root = ET.fromstring(xml_str)
                for elem in root.iter():
                    tag = elem.tag.lower()
                    if "protocol" in tag and "name" in tag:
                        val = (elem.text or "").strip()
                        if val:
                            metadata["protocol_name"] = val
                    elif tag in ("resolution", "pixel_size"):
                        val = (elem.text or "").strip()
                        if val:
                            metadata["resolution"] = val
            except ET.ParseError:
                pass  # Non-critical

        return metadata
