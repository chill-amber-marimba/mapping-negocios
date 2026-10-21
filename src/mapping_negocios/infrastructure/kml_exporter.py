"""KML exporter producing a bookmark list Organic Maps can import.

Organic Maps imports ``.kml``/``.kmz`` files opened from the file manager or a
share sheet, storing them as a local, private, offline bookmark list. Style ids
follow Organic Maps' own export format (``placemark-<color>``) so pins keep
their colors after import.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import polars as pl

from mapping_negocios.application.frames import LIST_SEPARATOR
from mapping_negocios.domain.models import Adherencia

KML_NS = "http://www.opengis.net/kml/2.2"
ICON_URL = "https://omaps.app/placemarks/placemark-{color}.png"
UNASSESSED_COLOR = "gray"

# Adherencia semaphore -> Organic Maps pin color.
ADHERENCIA_COLORS: dict[Adherencia, str] = {
    Adherencia.GREEN: "green",
    Adherencia.YELLOW: "yellow",
    Adherencia.RED: "red",
}
COLORS = (*ADHERENCIA_COLORS.values(), UNASSESSED_COLOR)

DESCRIPTION_FIELDS = {
    "formatted_address": "Address",
    "phone": "Phone",
    "website": "Website",
    "rating": "Rating",
    "user_rating_count": "Reviews",
    "primary_type": "Type",
    "adherencia": "Adherencia",
    "google_maps_uri": "Google Maps",
}


def color_for(adherencia: str | None) -> str:
    """Pick a pin color from a place's adherencia semaphore.

    Args:
        adherencia: An ``Adherencia`` value, or None if not assessed yet.

    Returns:
        An Organic Maps color name.
    """
    if adherencia is None:
        return UNASSESSED_COLOR
    return ADHERENCIA_COLORS[Adherencia(adherencia)]


class KmlExporter:
    """Writes the businesses DataFrame as a KML bookmark list."""

    extension = "kml"

    def export(self, frame: pl.DataFrame, path: Path, title: str) -> Path:
        """Write ``frame`` as KML with one placemark per business.

        Args:
            frame: Businesses DataFrame (``BUSINESS_SCHEMA``).
            path: Destination file.
            title: Bookmark list name shown in Organic Maps.

        Returns:
            The written path.
        """
        ET.register_namespace("", KML_NS)
        kml = ET.Element(f"{{{KML_NS}}}kml")
        document = ET.SubElement(kml, _tag("Document"))
        ET.SubElement(document, _tag("name")).text = title
        for color in COLORS:
            style = ET.SubElement(document, _tag("Style"), id=f"placemark-{color}")
            icon = ET.SubElement(ET.SubElement(style, _tag("IconStyle")), _tag("Icon"))
            ET.SubElement(icon, _tag("href")).text = ICON_URL.format(color=color)
        for row in frame.iter_rows(named=True):
            document.append(_placemark(row))

        tree = ET.ElementTree(kml)
        ET.indent(tree)
        path.parent.mkdir(parents=True, exist_ok=True)
        tree.write(path, encoding="utf-8", xml_declaration=True)
        return path


def _tag(name: str) -> str:
    return f"{{{KML_NS}}}{name}"


def _placemark(row: dict) -> ET.Element:
    placemark = ET.Element(_tag("Placemark"))
    ET.SubElement(placemark, _tag("name")).text = row["name"]
    ET.SubElement(placemark, _tag("description")).text = "\n".join(
        f"{label}: {row[key]}"
        for key, label in DESCRIPTION_FIELDS.items()
        if row.get(key) is not None
    )
    color = color_for(row["adherencia"])
    ET.SubElement(placemark, _tag("styleUrl")).text = f"#placemark-{color}"
    extended = ET.SubElement(placemark, _tag("ExtendedData"))
    for key, value in row.items():
        if value is None or key in {"name", "latitude", "longitude"}:
            continue
        data = ET.SubElement(extended, _tag("Data"), name=key)
        text = LIST_SEPARATOR.join(value) if isinstance(value, list) else str(value)
        ET.SubElement(data, _tag("value")).text = text
    point = ET.SubElement(placemark, _tag("Point"))
    ET.SubElement(
        point, _tag("coordinates")
    ).text = f"{row['longitude']},{row['latitude']}"
    return placemark
