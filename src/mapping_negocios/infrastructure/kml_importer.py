"""KML importer, the inverse of ``KmlExporter``.

Every placemark field but the name and point is read from ``ExtendedData``, so
only KML files written by ``KmlExporter`` (or keeping its data) round-trip.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import polars as pl

from mapping_negocios.application.frames import FLAT_BUSINESS_SCHEMA, unflatten
from mapping_negocios.infrastructure.kml_exporter import KML_NS

TEXT_SCHEMA = pl.Schema(dict.fromkeys(FLAT_BUSINESS_SCHEMA, pl.String))


class KmlImporter:
    """Reads a businesses KML back into a DataFrame."""

    extension = "kml"

    def read(self, path: Path) -> pl.DataFrame:
        """Read one row per placemark, forcing the expected schema.

        Args:
            path: KML file written by ``KmlExporter``.

        Returns:
            A DataFrame with ``BUSINESS_SCHEMA``.

        Raises:
            polars.exceptions.InvalidOperationError: If a value does not fit its
                column type, e.g. an unknown ``adherencia``.
        """
        placemarks = ET.parse(path).getroot().iter(_tag("Placemark"))
        rows = [_row(placemark) for placemark in placemarks]
        frame = pl.DataFrame(rows, schema=TEXT_SCHEMA).cast(FLAT_BUSINESS_SCHEMA)
        return unflatten(frame)


def _tag(name: str) -> str:
    return f"{{{KML_NS}}}{name}"


def _row(placemark: ET.Element) -> dict[str, str | None]:
    row: dict[str, str | None] = {
        data.get("name", ""): data.findtext(_tag("value")) or None
        for data in placemark.iter(_tag("Data"))
    }
    coordinates = placemark.findtext(f"{_tag('Point')}/{_tag('coordinates')}", "")
    longitude, latitude, *_ = coordinates.strip().split(",")
    row |= {
        "name": placemark.findtext(_tag("name")),
        "latitude": latitude,
        "longitude": longitude,
    }
    return row
