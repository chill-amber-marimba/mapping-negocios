"""Tests for CSV and KML exporters."""

import xml.etree.ElementTree as ET
from pathlib import Path

import polars as pl

from mapping_negocios.application.frames import businesses_to_frame
from mapping_negocios.infrastructure.csv_exporter import CsvExporter
from mapping_negocios.infrastructure.kml_exporter import KML_NS, KmlExporter, color_for

from fakes import make_business

NS = {"k": KML_NS}


def sample_frame() -> pl.DataFrame:
    """Two businesses, one with optional fields filled."""
    return businesses_to_frame(
        [
            make_business(
                "a",
                primary_type="cafe",
                types=("cafe", "food"),
                phone="+34 1",
                postal_code="28010",
            ),
            make_business("b", lat=40.015, lng=-3.785),
        ],
        "Test Town",
    )


def test_csv_round_trip(tmp_path: Path) -> None:
    """CSV is readable by polars and list columns are joined."""
    path = CsvExporter().export(sample_frame(), tmp_path / "out" / "x.csv", "ignored")
    frame = pl.read_csv(path, schema_overrides={"postal_code": pl.String})
    assert frame.height == 2
    assert frame["types"][0] == "cafe|food"
    assert frame["postal_code"][0] == "28010"


def test_kml_structure(tmp_path: Path) -> None:
    """KML has a named document, styles and one placemark per row."""
    path = KmlExporter().export(sample_frame(), tmp_path / "x.kml", "Test Town")
    root = ET.parse(path).getroot()
    assert root.findtext("k:Document/k:name", namespaces=NS) == "Test Town"
    style_ids = {s.get("id") for s in root.findall("k:Document/k:Style", NS)}
    assert {"placemark-red", "placemark-blue"} <= style_ids

    placemarks = root.findall("k:Document/k:Placemark", NS)
    assert [p.findtext("k:name", namespaces=NS) for p in placemarks] == [
        "Biz a",
        "Biz b",
    ]
    first, second = placemarks
    assert first.findtext("k:Point/k:coordinates", namespaces=NS) == "-3.79,40.01"
    assert first.findtext("k:styleUrl", namespaces=NS) == "#placemark-red"
    assert second.findtext("k:styleUrl", namespaces=NS) == "#placemark-blue"
    assert "Phone: +34 1" in (first.findtext("k:description", namespaces=NS) or "")
    data = {
        d.get("name"): d.findtext("k:value", namespaces=NS)
        for d in first.iter(f"{{{KML_NS}}}Data")
    }
    assert data["postal_code"] == "28010"
    assert data["types"] == "cafe|food"


def test_color_for() -> None:
    """First known type decides the color; unknown types get the default."""
    assert color_for(["establishment", "pharmacy"]) == "green"
    assert color_for(["establishment"]) == "blue"
    assert color_for(None) == "blue"
