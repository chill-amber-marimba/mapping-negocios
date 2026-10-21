"""KML exporter producing a bookmark list Organic Maps can import.

Organic Maps imports ``.kml``/``.kmz`` files opened from the file manager or a
share sheet, storing them as a local, private, offline bookmark list. Style ids
follow Organic Maps' own export format (``placemark-<color>``) so pins keep
their colors after import.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import polars as pl

KML_NS = "http://www.opengis.net/kml/2.2"
ICON_URL = "https://omaps.app/placemarks/placemark-{color}.png"
DEFAULT_COLOR = "blue"

# Google place type -> Organic Maps pin color. First match wins.
TYPE_COLORS: dict[str, str] = {
    "restaurant": "red",
    "cafe": "red",
    "bar": "red",
    "bakery": "red",
    "food": "red",
    "meal_takeaway": "red",
    "store": "orange",
    "shopping_mall": "orange",
    "supermarket": "orange",
    "grocery_store": "orange",
    "clothing_store": "orange",
    "health": "green",
    "pharmacy": "green",
    "doctor": "green",
    "dentist": "green",
    "hospital": "green",
    "gym": "green",
    "lodging": "purple",
    "hotel": "purple",
    "bank": "yellow",
    "atm": "yellow",
    "finance": "yellow",
}
COLORS = (*sorted(set(TYPE_COLORS.values())), DEFAULT_COLOR)

DESCRIPTION_FIELDS = {
    "formatted_address": "Address",
    "phone": "Phone",
    "website": "Website",
    "rating": "Rating",
    "user_rating_count": "Reviews",
    "primary_type": "Type",
    "google_maps_uri": "Google Maps",
}


def color_for(types: list[str] | None) -> str:
    """Pick a pin color from a place's types.

    Args:
        types: Google place types, primary type first.

    Returns:
        An Organic Maps color name.
    """
    return next(
        (TYPE_COLORS[t] for t in types or [] if t in TYPE_COLORS), DEFAULT_COLOR
    )


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
    types = (
        [row["primary_type"], *(row["types"] or [])]
        if row["primary_type"]
        else row["types"]
    )
    ET.SubElement(placemark, _tag("styleUrl")).text = f"#placemark-{color_for(types)}"
    extended = ET.SubElement(placemark, _tag("ExtendedData"))
    for key, value in row.items():
        if value is None or key in {"name", "latitude", "longitude"}:
            continue
        data = ET.SubElement(extended, _tag("Data"), name=key)
        text = "|".join(value) if isinstance(value, list) else str(value)
        ET.SubElement(data, _tag("value")).text = text
    point = ET.SubElement(placemark, _tag("Point"))
    ET.SubElement(
        point, _tag("coordinates")
    ).text = f"{row['longitude']},{row['latitude']}"
    return placemark
