"""Tests for CSV and KML importers (round trips through the exporters)."""

from pathlib import Path

import polars as pl
import pytest
from polars.exceptions import ComputeError, InvalidOperationError
from polars.testing import assert_frame_equal

from mapping_negocios.application.frames import BUSINESS_SCHEMA, businesses_to_frame
from mapping_negocios.domain.models import Adherencia, Business, Coordinates
from mapping_negocios.infrastructure.csv_exporter import CsvExporter
from mapping_negocios.infrastructure.csv_importer import CsvImporter
from mapping_negocios.infrastructure.kml_exporter import KmlExporter
from mapping_negocios.infrastructure.kml_importer import KmlImporter

from fakes import make_business


def sample_frame() -> pl.DataFrame:
    """A fully filled business, an empty one and an empty ``types`` list."""
    full = Business(
        place_id="a",
        name='Café Ñandú, "El Bueno"',
        location=Coordinates(40.4321987, -3.7012345),
        primary_type="cafe",
        types=("cafe", "food"),
        formatted_address="Calle Mayor 1, 28010 Madrid",
        postal_code="02810",
        locality="Madrid",
        admin_region="Comunidad de Madrid",
        country="ES",
        phone="+34 1",
        website="https://example.com/?a=1&b=2",
        rating=4.5,
        user_rating_count=123,
        business_status="OPERATIONAL",
        google_maps_uri="https://maps.google.com/?cid=1",
        adherencia=Adherencia.YELLOW,
    )
    return businesses_to_frame(
        [full, make_business("b", adherencia=Adherencia.RED), make_business("c")],
        "Test Town",
    )


@pytest.mark.parametrize(
    ("exporter", "importer"),
    [(CsvExporter(), CsvImporter()), (KmlExporter(), KmlImporter())],
    ids=["csv", "kml"],
)
def test_round_trip(
    exporter: CsvExporter | KmlExporter,
    importer: CsvImporter | KmlImporter,
    tmp_path: Path,
) -> None:
    """Reading an exported file gives back the same DataFrame."""
    frame = sample_frame()
    path = exporter.export(frame, tmp_path / f"x.{exporter.extension}", "Test Town")
    assert_frame_equal(importer.read(path), frame)


@pytest.mark.parametrize(
    ("exporter", "importer"),
    [(CsvExporter(), CsvImporter()), (KmlExporter(), KmlImporter())],
    ids=["csv", "kml"],
)
def test_round_trip_empty(
    exporter: CsvExporter | KmlExporter,
    importer: CsvImporter | KmlImporter,
    tmp_path: Path,
) -> None:
    """An empty export reads back as an empty, typed DataFrame."""
    frame = businesses_to_frame([], "Test Town")
    path = exporter.export(frame, tmp_path / f"x.{exporter.extension}", "Test Town")
    imported = importer.read(path)
    assert imported.is_empty()
    assert imported.schema == BUSINESS_SCHEMA


def test_csv_rejects_unknown_adherencia(tmp_path: Path) -> None:
    """Values outside the semaphore fail when reading a CSV."""
    path = CsvExporter().export(sample_frame(), tmp_path / "x.csv", "ignored")
    path.write_text(path.read_text().replace("yellow", "blue"))
    with pytest.raises(ComputeError):
        CsvImporter().read(path)


def test_kml_rejects_unknown_adherencia(tmp_path: Path) -> None:
    """Values outside the semaphore fail when reading a KML."""
    path = KmlExporter().export(sample_frame(), tmp_path / "x.kml", "Test Town")
    text = path.read_text().replace("<value>yellow</value>", "<value>blue</value>")
    path.write_text(text)
    with pytest.raises(InvalidOperationError):
        KmlImporter().read(path)
