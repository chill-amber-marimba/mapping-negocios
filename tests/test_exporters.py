"""Tests for CSV and KML exporters."""

import xml.etree.ElementTree as ET
from pathlib import Path

import polars as pl

from mapping_negocios.application.frames import businesses_to_frame
from mapping_negocios.domain.models import Adherencia
from mapping_negocios.infrastructure.csv_exporter import CsvExporter
from mapping_negocios.infrastructure.kml_exporter import (
    KML_NS,
    ColorBy,
    KmlExporter,
    adherencia_color,
    type_color,
)

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
                adherencia=Adherencia.GREEN,
            ),
            make_business("b", lat=40.015, lng=-3.785),
        ],
        "Test Town",
    )


def test_frame_adherencia_is_enum() -> None:
    """Adherencia is a semaphore enum column; unassessed businesses are null."""
    frame = sample_frame()
    assert frame.schema["adherencia"] == pl.Enum(["green", "yellow", "red"])
    assert frame["adherencia"].to_list() == ["green", None]


def test_csv_round_trip(tmp_path: Path) -> None:
    """CSV is readable by polars and list columns are joined."""
    path = CsvExporter().export(sample_frame(), tmp_path / "out" / "x.csv", "ignored")
    frame = pl.read_csv(path, schema_overrides={"postal_code": pl.String})
    assert frame.height == 2
    assert frame["types"][0] == "cafe|food"
    assert frame["postal_code"][0] == "28010"
    assert frame["adherencia"][0] == "green"


def test_kml_structure(tmp_path: Path) -> None:
    """KML has a named document, styles and one placemark per row."""
    path = KmlExporter().export(sample_frame(), tmp_path / "x.kml", "Test Town")
    root = ET.parse(path).getroot()
    assert root.findtext("k:Document/k:name", namespaces=NS) == "Test Town"
    style_ids = {s.get("id") for s in root.findall("k:Document/k:Style", NS)}
    assert style_ids == {
        "placemark-green",
        "placemark-yellow",
        "placemark-red",
        "placemark-gray",
    }

    placemarks = root.findall("k:Document/k:Placemark", NS)
    assert [p.findtext("k:name", namespaces=NS) for p in placemarks] == [
        "Biz a",
        "Biz b",
    ]
    first, second = placemarks
    assert first.findtext("k:Point/k:coordinates", namespaces=NS) == "-3.79,40.01"
    assert first.findtext("k:styleUrl", namespaces=NS) == "#placemark-green"
    assert second.findtext("k:styleUrl", namespaces=NS) == "#placemark-gray"
    assert "Phone: +34 1" in (first.findtext("k:description", namespaces=NS) or "")
    data = {
        d.get("name"): d.findtext("k:value", namespaces=NS)
        for d in first.iter(f"{{{KML_NS}}}Data")
    }
    assert data["postal_code"] == "28010"
    assert data["types"] == "cafe|food"


def test_kml_colored_by_type(tmp_path: Path) -> None:
    """With ``ColorBy.TYPE`` pins follow the business type, not adherencia."""
    path = KmlExporter(ColorBy.TYPE).export(sample_frame(), tmp_path / "x.kml", "T")
    root = ET.parse(path).getroot()
    style_ids = {s.get("id") for s in root.findall("k:Document/k:Style", NS)}
    assert style_ids == {
        f"placemark-{color}"
        for color in ("red", "orange", "green", "purple", "yellow", "blue")
    }
    first, second = root.findall("k:Document/k:Placemark", NS)
    # The cafe is green by adherencia but red (food & drink) by type.
    assert first.findtext("k:styleUrl", namespaces=NS) == "#placemark-red"
    assert second.findtext("k:styleUrl", namespaces=NS) == "#placemark-blue"


def test_adherencia_color() -> None:
    """Adherencia decides the color; unassessed businesses are gray."""
    assert adherencia_color("green") == "green"
    assert adherencia_color("yellow") == "yellow"
    assert adherencia_color("red") == "red"
    assert adherencia_color(None) == "gray"


def test_type_color() -> None:
    """First known type decides the color; unknown types get the default."""
    assert type_color(["establishment", "pharmacy"]) == "green"
    assert type_color(["establishment"]) == "blue"
    assert type_color(None) == "blue"
